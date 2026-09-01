import os
import requests
import random

from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from drf_yasg.utils import swagger_auto_schema

from rest_framework_simplejwt.tokens import RefreshToken

from django.conf import settings

from .serializers import UserEventSerializer, UserEventListSerializer, UserQuestionAnswerResponseSerializer, UserQuestionAnswerSerializer, UserQuestionAnswerUpdateSerializer, UserQuestionRequestSerializer, UserQuestionGetSerializer, LoginSerializer, EventListSerializer, QuestionSerializer
from .models import Event, Question, ScoreDispatch, User_Event, User_Question, User_Token
from .tasks import process_result
# Create your views here.

User = get_user_model()

class LoginView(APIView):
    """LOGIN API VIEW THAT ACCEPTS EMAIL
    AND PASSWORD AND RETURNS A TOKEN"""
    @swagger_auto_schema(request_body=LoginSerializer)
    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        password = request.data.get('password')

        if not email or not password:
            return Response(data={'error': 'invalid data'},
                            status=status.HTTP_400_BAD_REQUEST)            

        url = '{}/user/signin'.format(os.environ.get('EMS_API'))
        data = {
            'email': email,
            'password': password
        }
        res = requests.post(url, data=data, verify=False)
        if res.status_code == status.HTTP_401_UNAUTHORIZED:
            return Response(data=res.json(),
                            status=status.HTTP_401_UNAUTHORIZED)
        elif res.status_code == status.HTTP_404_NOT_FOUND:
            return Response(data=res.json(), status=status.HTTP_404_NOT_FOUND)

        # get user
        try:
            user = User.objects.get(username=email)
        except User.DoesNotExist:
            user = User.objects.create_user(username=email,
                                            email=email, password=password)
            user.first_name = res.json().get('user').get('first_name')
            user.last_name = res.json().get('user').get('last_name')
            user.save()
        # Create user_token object for future use
        # User_Token.objects.create(fk_user=user, token=res.json().get('token'))

        if res.status_code == status.HTTP_200_OK:
            token = res.json().get('token')
            # query my events
            url = '{}/user_events'.format(os.environ.get('EMS_API'))
            myevent_res = requests.get(url, headers={
                'Authorization': 'Bearer ' + token}, verify=False)

            if myevent_res.status_code == status.HTTP_401_UNAUTHORIZED:
                return Response(data=myevent_res.json(),
                                status=status.HTTP_401_UNAUTHORIZED)

            events = myevent_res.json().get('events')
            for event in events:
                try:
                    slot_id = event.get('fk_slot')
                except TypeError:
                    slot_id = None

                if slot_id:
                    try:
                        event = Event.objects.get(external_slot_id=slot_id)
                        # create user contest
                        ue, _ = User_Event.objects.get_or_create(
                        fk_user=user, fk_event=event)
                    except Event.DoesNotExist:
                        continue

            # create jwt token
            refresh = RefreshToken.for_user(user)

            data = {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
            return Response(data=data, status=status.HTTP_200_OK)


class UserEventListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    """API VIEW THAT RETURNS USER ALL USER EVENTS"""
    @swagger_auto_schema(
        operation_description="Returns user events",
        responses={
            200: UserEventListSerializer(many=True)
        }
    )
    def get(self, request, *args, **kwargs):
        user = request.user
        user_events = User_Event.objects.filter(fk_user=user).select_related('fk_event')
        for user_event in user_events:
            now = timezone.now()
            if user_event.fk_event.start_time <= now <= user_event.fk_event.end_time:
                user_event.started = True
            if user_event.fk_event.end_time < now and not user_event.finished:
                user_event.finished = True
                user_event.save(update_fields=['finished', 'updated_at'])
                process_result.apply_async(kwargs={'user_event_id': user_event.id})
            elif user_event.started:
                user_event.save(update_fields=['started', 'updated_at'])
        serializer = UserEventListSerializer(user_events, many=True)
        return Response(data=serializer.data, status=status.HTTP_200_OK)


class UserEventGetView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    """API VIEW THAT RETURNS USER EVENT BY ID"""
    @swagger_auto_schema(
        operation_description="Returns user event by id",
        responses={
            200: UserEventSerializer()
        }
    )
    def get(self, request, id):
        user = request.user
        try:
            user_event = User_Event.objects.get(fk_user=user, id=id, started=True, finished=False)
            if user_event.fk_event.end_time < timezone.now():
                return Response(data={'error': 'event finished'},
                                status=status.HTTP_403_FORBIDDEN)

        except User_Event.DoesNotExist:
            return Response(data={'error': 'event finished or not started yet'},
                            status=status.HTTP_403_FORBIDDEN)

        serializer = UserEventSerializer(instance=user_event)   
        return Response(data=serializer.data, status=status.HTTP_200_OK)


class UserQuestionAnswer(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _update(self, request, uq_id, data=None):
        # validate before mutation
        data = data if data is not None else request.data
        upd = UserQuestionAnswerUpdateSerializer(data=data)
        if not upd.is_valid():
            return Response(data=upd.errors, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            uq = User_Question.objects.select_for_update().filter(id=uq_id, fk_user=request.user).first()
            if not uq:
                return Response(data={'detail': 'Question assignment not found.'}, status=status.HTTP_404_NOT_FOUND)
            # ponytail: avoid FOR UPDATE on outer join (fk_event nullable)
            q = Question.objects.select_related('fk_event').get(id=uq.fk_question_id)
            ev = q.fk_event
            now = timezone.now()
            # lock matching User_Event
            ue = User_Event.objects.select_for_update().filter(fk_user=request.user, fk_event=ev).first() if ev else None
            if not ue or not ue.started or ue.submitted_at or ue.finished or not ev or ev.start_time > now or ev.end_time <= now:
                return Response(data={'detail': 'Event is not accepting answers.'}, status=status.HTTP_403_FORBIDDEN)
            # save only provided fields
            for k, v in upd.validated_data.items():
                setattr(uq, k, v)
            uq.save(update_fields=list(upd.validated_data.keys()) + ["updated_at"])
            resp = UserQuestionAnswerResponseSerializer(uq)
            return Response(data=resp.data, status=status.HTTP_200_OK)

    @swagger_auto_schema(
        request_body=UserQuestionAnswerUpdateSerializer,
        responses={200: UserQuestionAnswerResponseSerializer, 400: "bad", 401: "auth", 403: "forbidden", 404: "not found"},
        manual_parameters=[],
    )
    def patch(self, request, id=None, *args, **kwargs):  # ponytail: canonical path param
        uq_id = id or request.data.get("id")
        if not uq_id:
            return Response(data={'detail': 'Missing id.'}, status=status.HTTP_400_BAD_REQUEST)
        is_legacy = id is None
        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        if is_legacy:
            data.pop("id", None)
            data.pop("fk_question", None)
        resp = self._update(request, uq_id, data=data)
        if is_legacy:
            sunset = getattr(settings, "MCQ_LEGACY_ANSWER_SUNSET", "")
            if sunset:
                resp["Deprecation"] = "true"
                resp["Sunset"] = sunset
        return resp


class UserQuestionListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    """API VIEW THAT RETURNS USER QUESTIONS"""
    @swagger_auto_schema(
        operation_description="Returns user questions",
        responses={
            200: UserQuestionGetSerializer(many=True)
        }
    )
    def get(self, request, id, *args, **kwargs):
        user = request.user
        now = timezone.now()
        with transaction.atomic():
            ue = User_Event.objects.select_for_update().select_related('fk_event').filter(id=id, fk_user=user).first()
            if not ue:
                return Response(data={'error': 'not found'}, status=status.HTTP_404_NOT_FOUND)
            ev = ue.fk_event
            if ue.submitted_at or ue.finished:
                return Response(data={'error': 'event submitted already'}, status=status.HTTP_403_FORBIDDEN)
            if ev.start_time > now or ev.end_time <= now:  # ponytail: [start,end) + submitted check
                return Response(data={'error': 'event not accepting questions'}, status=status.HTTP_403_FORBIDDEN)
            uqs = User_Question.objects.filter(fk_user=user, fk_question__fk_event=ev)
            if uqs.exists():
                serializer = UserQuestionGetSerializer(uqs, many=True)
                return Response(data=serializer.data, status=status.HTTP_200_OK)
            questions = list(Question.objects.filter(fk_event=ev))
            if not questions:
                return Response(status=status.HTTP_400_BAD_REQUEST)
            random_questions = random.sample(questions, min(ev.no_of_questions, len(questions)))
            try:
                User_Question.objects.bulk_create([User_Question(fk_user=user, fk_question=q) for q in random_questions])
                # ponytail: set started only after valid assignment
                if not ue.started:
                    ue.started = True
                    ue.save(update_fields=["started", "updated_at"])
                    if user.current_user_event != ue.id:
                        user.current_user_event = ue.id
                        user.save(update_fields=["current_user_event"])
                uqs = User_Question.objects.filter(fk_user=user, fk_question__fk_event=ev)
                serializer = UserQuestionGetSerializer(uqs, many=True)
                return Response(data=serializer.data, status=status.HTTP_200_OK)
            except IntegrityError:
                uqs = User_Question.objects.filter(fk_user=user, fk_question__fk_event=ev)
                serializer = UserQuestionGetSerializer(uqs, many=True)
                return Response(data=serializer.data, status=status.HTTP_200_OK)
        return Response(status=status.HTTP_400_BAD_REQUEST)


class UserSubmitEventView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    """API VIEW THAT STARTS SUBMISSIONS PROCESS"""
    def _submit(self, request, id):
        user = request.user
        now = timezone.now()
        with transaction.atomic():
            ue = User_Event.objects.select_for_update().select_related('fk_event').filter(id=id, fk_user=user).first()
            if not ue:
                return Response(data={'error': 'not found'}, status=status.HTTP_404_NOT_FOUND)
            ev = ue.fk_event
            if ev.start_time > now or ev.end_time <= now:
                return Response(data={'error': 'event not accepting submissions'}, status=status.HTTP_403_FORBIDDEN)
            if ue.submitted_at or ue.finished:
                return Response(data={"success": "Test submitted successfully!"}, status=status.HTTP_200_OK)  # ponytail: idempotent
            ue.started = True
            ue.finished = True
            ue.submitted_at = now
            ue.save(update_fields=["started", "finished", "submitted_at", "updated_at"])
            if str(user.current_user_event) == str(ue.id):
                user.current_user_event = None
                user.save(update_fields=["current_user_event"])
            dispatch, _ = ScoreDispatch.objects.get_or_create(fk_user_event=ue, defaults={"status": ScoreDispatch.PENDING})
            if dispatch.status != ScoreDispatch.PENDING:
                dispatch.status = ScoreDispatch.PENDING
                dispatch.save(update_fields=["status", "updated_at"])
            transaction.on_commit(lambda: process_result.delay(user_event_id=str(ue.id)))
        return Response(data={"success": "Test submitted successfully!"}, status=status.HTTP_200_OK)

    def post(self, request, id, *args, **kwargs):
        return self._submit(request, id)

    def get(self, request, id, *args, **kwargs):  # ponytail: retain GET one release, idempotent
        return self._submit(request, id)
