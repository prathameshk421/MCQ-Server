from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from core.models import User_Event, User_Question, User_Result, ScoreDispatch

class Command(BaseCommand):
    help = "Deterministic duplicate repair + submitted_at backfill"

    def handle(self, *args, **options):
        # User_Question: keep newest answered else newest
        with transaction.atomic():
            dup_keys = User_Question.objects.values("fk_user", "fk_question").annotate(c=Count("id")).filter(c__gt=1)
            for k in dup_keys:
                qs = User_Question.objects.filter(fk_user=k["fk_user"], fk_question=k["fk_question"]).order_by("-updated_at", "-created_at")
                # ponytail: newest answered first, else newest
                answered = [x for x in qs if x.answer is not None]
                keep = answered[0] if answered else qs[0]
                User_Question.objects.filter(fk_user=k["fk_user"], fk_question=k["fk_question"]).exclude(id=keep.id).delete()

            # User_Event: keep submitted/finished duplicate else oldest
            dup_ue = User_Event.objects.values("fk_user", "fk_event").annotate(c=Count("id")).filter(c__gt=1)
            for k in dup_ue:
                qs = User_Event.objects.filter(fk_user=k["fk_user"], fk_event=k["fk_event"]).order_by("created_at")
                # prefer submitted/finished
                finished = qs.filter(finished=True) or qs.filter(submitted_at__isnull=False)
                keep = finished.order_by("-submitted_at", "-updated_at").first() if finished.exists() else qs.first()
                # keep canonical
                others = User_Event.objects.filter(fk_user=k["fk_user"], fk_event=k["fk_event"]).exclude(id=keep.id)
                # delete duplicate results for others
                User_Result.objects.filter(fk_user_event__in=others).delete()
                # delete duplicates
                others.delete()
                # ensure one pending dispatch for canonical submitted event
                if keep.finished or keep.submitted_at:
                    ScoreDispatch.objects.get_or_create(fk_user_event=keep, defaults={"status": ScoreDispatch.PENDING})

            # delete duplicate results per user_event (keep first)
            dup_res = User_Result.objects.values("fk_user_event").annotate(c=Count("id")).filter(c__gt=1)
            for k in dup_res:
                qs = User_Result.objects.filter(fk_user_event=k["fk_user_event"]).order_by("created_at")
                keep = qs.first()
                User_Result.objects.filter(fk_user_event=k["fk_user_event"]).exclude(id=keep.id).delete()
                # ensure dispatch for canonical submitted
                try:
                    ue = User_Event.objects.get(id=k["fk_user_event"])
                    if ue.finished or ue.submitted_at:
                        ScoreDispatch.objects.get_or_create(fk_user_event=ue, defaults={"status": ScoreDispatch.PENDING})
                except User_Event.DoesNotExist:
                    pass

            # backfill legacy finished rows
            for ue in User_Event.objects.filter(finished=True, submitted_at__isnull=True):
                ue.submitted_at = ue.updated_at or ue.created_at or timezone.now()
                ue.save(update_fields=["submitted_at"])

            # ensure pending dispatch for all submitted without one
            for ue in User_Event.objects.filter(submitted_at__isnull=False):
                ScoreDispatch.objects.get_or_create(fk_user_event=ue, defaults={"status": ScoreDispatch.PENDING})

        self.stdout.write("repair done")
