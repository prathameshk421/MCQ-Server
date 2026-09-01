from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Event, Question, User_Event, User_Question, User_Result
from .serializers import UserQuestionAnswerUpdateSerializer, UserQuestionAnswerSerializer
from .tasks import process_result


class McqIntegrityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='learner', password='password')
        self.other_user = get_user_model().objects.create_user(username='other', password='password')
        now = timezone.now()
        self.event = Event.objects.create(
            name='Python basics', external_event_id='event-1', external_slot_id='slot-1',
            start_time=now - timedelta(minutes=5), end_time=now + timedelta(minutes=30),
        )
        self.question = Question.objects.create(
            statement='2 + 2 = ?', options=['1', '2', '3', '4'], correct_option=3,
            fk_event=self.event,
        )
        self.user_event = User_Event.objects.create(fk_user=self.user, fk_event=self.event, started=True)
        self.user_question = User_Question.objects.create(fk_user=self.user, fk_question=self.question)

    def test_answer_payload_rejects_out_of_range_option(self):
        serializer = UserQuestionAnswerUpdateSerializer(data={'answer': 4})
        self.assertFalse(serializer.is_valid())
        self.assertIn('answer', serializer.errors)
        # also test legacy alias
        serializer2 = UserQuestionAnswerSerializer(data={'answer': 4})
        self.assertFalse(serializer2.is_valid())

    def test_user_cannot_answer_another_users_question(self):
        client = APIClient()
        client.force_authenticate(self.other_user)
        response = client.patch(
            '/api/question/answer', {'id': str(self.user_question.id), 'answer': 3}, format='json'
        )
        self.assertEqual(response.status_code, 404)
        self.user_question.refresh_from_db()
        self.assertIsNone(self.user_question.answer)

    def test_user_event_and_assignment_are_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User_Event.objects.create(fk_user=self.user, fk_event=self.event)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User_Question.objects.create(fk_user=self.user, fk_question=self.question)

    def test_result_processing_is_idempotent(self):
        self.user_question.answer = 3
        self.user_question.save()
        # ponytail: mark submitted so scoring runs
        self.user_event.submitted_at = timezone.now()
        self.user_event.finished = True
        self.user_event.save(update_fields=["submitted_at", "finished"])
        process_result.run(user_event_id=self.user_event.id)
        process_result.run(user_event_id=self.user_event.id)
        self.assertEqual(User_Result.objects.filter(fk_user_event=self.user_event).count(), 1)
        self.assertEqual(User_Result.objects.get(fk_user_event=self.user_event).score, 1)
