import json
from django.core.management.base import BaseCommand
from django.db.models import Count, F
from core.models import Event, Question, User_Event, User_Question, User_Result

class Command(BaseCommand):
    help = "Audit MCQ integrity, emit JSON, exit non-zero on violations"

    def handle(self, *args, **options):
        errors = {}
        invalid_events = list(Event.objects.filter(start_time__gte=F("end_time")).values_list("id", flat=True))
        if invalid_events:
            errors["invalid_event_ranges"] = [str(i) for i in invalid_events]

        # question checks: not exactly four / non-empty / correct_option outside 0..3
        bad_questions = []
        for q in Question.objects.all().only("id", "options", "correct_option"):
            opts = q.options or []
            if len(opts) != 4 or any(not (isinstance(o, str) and o.strip()) for o in opts):
                bad_questions.append(str(q.id))
            elif not 0 <= q.correct_option <= 3:
                bad_questions.append(str(q.id))
        if bad_questions:
            errors["bad_questions"] = bad_questions

        # answers outside 0..3
        bad_answers = list(User_Question.objects.filter(answer__isnull=False).exclude(answer__gte=0, answer__lt=4).values_list("id", flat=True))
        if bad_answers:
            errors["bad_answers"] = [str(i) for i in bad_answers]

        # duplicates
        dup_user_event = list(User_Event.objects.values("fk_user", "fk_event").annotate(c=Count("id")).filter(c__gt=1).values_list("fk_user", "fk_event"))
        if dup_user_event:
            errors["duplicate_user_event"] = ["%s/%s" % (u, e) for u, e in dup_user_event]
        dup_user_question = list(User_Question.objects.values("fk_user", "fk_question").annotate(c=Count("id")).filter(c__gt=1).values_list("fk_user", "fk_question"))
        if dup_user_question:
            errors["duplicate_user_question"] = ["%s/%s" % (u, q) for u, q in dup_user_question]
        dup_result = list(User_Result.objects.values("fk_user_event").annotate(c=Count("id")).filter(c__gt=1).values_list("fk_user_event", flat=True))
        if dup_result:
            errors["duplicate_result"] = [str(i) for i in dup_result]

        self.stdout.write(json.dumps(errors, indent=2))
        if errors:
            # ponytail: exit non-zero signals CI failure
            import sys
            sys.exit(1)
