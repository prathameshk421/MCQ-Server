import random

from celery import shared_task
from django.db import OperationalError, transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import ScoreDispatch, User_Event, User_Question, User_Result


@shared_task(bind=True, max_retries=5, soft_time_limit=60, time_limit=75, queue="mcq-results", acks_late=True, reject_on_worker_lost=True)
def process_result(self, user_event_id=None, **kwargs):  # ponytail: idempotent, single query, outbox-aware
    uid = user_event_id or kwargs.get("user_event_id")
    if not uid:
        return 0
    try:
        with transaction.atomic():
            ue = User_Event.objects.select_for_update().get(id=uid)
            if not ue.submitted_at and not ue.finished:
                return 0
            # lock dispatch if exists
            sd = ScoreDispatch.objects.select_for_update().filter(fk_user_event=ue).first()
            # single query: count where answer == correct_option
            score = User_Question.objects.filter(fk_user=ue.fk_user, fk_question__fk_event=ue.fk_event, answer=F("fk_question__correct_option")).count()
            obj, _ = User_Result.objects.update_or_create(fk_user_event=ue, defaults={"score": score})
            if sd:
                sd.status = ScoreDispatch.COMPLETED
                sd.completed_at = timezone.now()
                sd.last_error = ""
                sd.save(update_fields=["status", "completed_at", "last_error", "updated_at"])
            return score
    except OperationalError as e:  # ponytail: transient only, retry with jitter
        if self.request.retries < self.max_retries:
            countdown = (2 ** self.request.retries) + random.uniform(0, 1)
            raise self.retry(exc=e, countdown=countdown)
        # mark dispatch failed if retries exhausted
        try:
            with transaction.atomic():
                sd = ScoreDispatch.objects.select_for_update().filter(fk_user_event_id=uid).first()
                if sd:
                    sd.status = ScoreDispatch.FAILED
                    sd.attempts = sd.attempts + 1
                    sd.last_error = str(e)[:500]
                    sd.save(update_fields=["status", "attempts", "last_error", "updated_at"])
        except Exception:
            pass
        raise
    except ScoreDispatch.DoesNotExist:
        pass


@shared_task(queue="mcq-maintenance")
def dispatch_pending_scores():  # ponytail: outbox recovery, at most 100 per minute
    now = timezone.now()
    cutoff = now - timezone.timedelta(minutes=5)
    with transaction.atomic():
        dispatches = list(
            ScoreDispatch.objects.select_for_update(skip_locked=True)
            .filter(Q(status=ScoreDispatch.PENDING) | Q(status=ScoreDispatch.FAILED) | Q(status=ScoreDispatch.QUEUED, queued_at__lt=cutoff))
            .order_by("updated_at")[:100]
        )
        for sd in dispatches:
            sd.status = ScoreDispatch.QUEUED
            sd.queued_at = now
            sd.attempts += 1
            sd.save(update_fields=["status", "queued_at", "attempts", "updated_at"])

    for sd in dispatches:
        try:
            # ponytail: after commit publish; no double queue
            def _pub(sid=str(sd.fk_user_event_id)):
                try:
                    process_result.delay(user_event_id=sid)
                except Exception as e:
                    with transaction.atomic():
                        obj = ScoreDispatch.objects.select_for_update().get(id=sd.id)
                        obj.status = ScoreDispatch.FAILED
                        obj.last_error = str(e)[:500]
                        obj.save(update_fields=["status", "last_error", "updated_at"])

            transaction.on_commit(_pub)
        except Exception as e:
            with transaction.atomic():
                obj = ScoreDispatch.objects.select_for_update().get(id=sd.id)
                obj.status = ScoreDispatch.FAILED
                obj.last_error = str(e)[:500]
                obj.save(update_fields=["status", "last_error", "updated_at"])
