from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.contrib.postgres.fields import ArrayField
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser

import uuid

class User(AbstractUser):
    current_user_event = models.UUIDField(null=True)

# Create your models here.
class Event(models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    name = models.CharField(max_length=50)
    image_url = models.URLField(null=True, blank=True)
    external_event_id = models.CharField(max_length=100)
    external_slot_id = models.CharField(max_length=100, null=True, blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    no_of_questions = models.PositiveIntegerField(default=20)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    rules = models.TextField(null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(end_time__gt=F('start_time')),
                name='event_end_after_start',
            ),
            models.UniqueConstraint(
                fields=['external_slot_id'],
                condition=Q(external_slot_id__isnull=False),
                name='unique_external_slot_id',
            ),
        ]
        indexes = [models.Index(fields=['start_time', 'end_time'], name='core_event_start_t_315f28_idx')]


class Question(models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    statement = models.TextField()
    options = ArrayField(models.TextField(), size=4)
    code = models.TextField(null=True, blank=True)
    image_url = models.URLField(null=True, blank=True)
    correct_option = models.PositiveIntegerField()
    fk_event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        opts = [(o.strip() if isinstance(o, str) else "") for o in (self.options or [])]
        if len(opts) != 4 or any(not o for o in opts):
            raise ValidationError({'options': 'Exactly four trimmed non-empty options are required.'})
        if not 0 <= self.correct_option <= 3:
            raise ValidationError({'correct_option': 'Use a zero-based option index between 0 and 3.'})

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(correct_option__gte=0) & Q(correct_option__lt=4),
                name='question_correct_option_in_range',
            ),
            models.CheckConstraint(
                check=Q(options__len=4),
                name='question_options_length_is_four',
            ),
        ]
        indexes = [models.Index(fields=['fk_event', 'created_at'], name='core_questi_fk_even_750586_idx')]


class User_Question(models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    fk_question = models.ForeignKey(Question, on_delete=models.CASCADE)
    fk_user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    answer = models.PositiveIntegerField(null=True)
    review_status = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['fk_user', 'fk_question'],
                name='unique_user_question',
            ),
            models.CheckConstraint(
                check=Q(answer__isnull=True) | (Q(answer__gte=0) & Q(answer__lt=4)),
                name='user_answer_in_range',
            ),
        ]
        indexes = [models.Index(fields=['fk_user', 'fk_question'], name='core_user_q_fk_user_f2b097_idx')]


class User_Event(models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    fk_user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    fk_event = models.ForeignKey(Event, on_delete=models.CASCADE)
    started = models.BooleanField(default=False)
    finished = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)  # ponytail: nullable for legacy backfill
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['fk_user', 'fk_event'],
                name='unique_user_event',
            ),
        ]
        indexes = [models.Index(fields=['fk_user', 'finished'], name='core_user_e_fk_user_6a7de0_idx')]


class ScoreDispatch(models.Model):  # ponytail: outbox covers Redis loss, single table
    PENDING = "pending"
    QUEUED = "queued"
    COMPLETED = "completed"
    FAILED = "failed"
    STATUS_CHOICES = [(PENDING, "pending"), (QUEUED, "queued"), (COMPLETED, "completed"), (FAILED, "failed")]
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    fk_user_event = models.OneToOneField(User_Event, on_delete=models.CASCADE, related_name="score_dispatch")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(null=True, blank=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['status', 'updated_at'], name='core_scored_status_8a1d2f_idx')]


class QuestionImportAudit(models.Model):  # ponytail: minimal audit, add fields only when needed
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    fk_event = models.ForeignKey(Event, on_delete=models.CASCADE)
    actor = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True)
    filename = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class User_Result(models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    fk_user_event = models.ForeignKey(User_Event, on_delete=models.CASCADE)
    score = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['fk_user_event'],
                name='unique_result_per_user_event',
            ),
        ]


class User_Token(models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    fk_user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    token = models.CharField(max_length=500)
    is_valid = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
