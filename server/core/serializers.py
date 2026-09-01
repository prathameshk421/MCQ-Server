from rest_framework import serializers
from djoser.serializers import UserSerializer
from django.contrib.auth import get_user_model

from .models import Question, User_Event, Event, User_Question

User = get_user_model()
class CustomUserSerializer(UserSerializer):
    class Meta(UserSerializer.Meta): 
        model = User
        fields = (
            'id',
            'email',
            'username',
            'current_user_event',
        )
        read_only_fields = ['current_user_event']

class LoginSerializer(serializers.Serializer):
    email = serializers.CharField(max_length=100)
    password = serializers.CharField(max_length=100)

    
class EventListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ['id', 'name', 'start_time', 'end_time', 'external_event_id', 'external_slot_id', 'image_url', 'rules']

class UserEventListSerializer(serializers.ModelSerializer):
    fk_event = EventListSerializer()

    class Meta:
        model = User_Event
        fields = ['id', 'fk_event', 'started','finished']


class UserEventSerializer(serializers.ModelSerializer):
    fk_event = EventListSerializer(many=False)

    class Meta:
        model = User_Event
        fields = ['id', 'fk_event', 'started', 'finished']


class UserQuestionRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = User_Question
        fields = ['id', 'fk_question', 'answer', 'review_status']

class QuestionSerializer(serializers.ModelSerializer):
    fk_event = EventListSerializer()
    
    class Meta: 
        model = Question
        fields = ['id', 'statement','code','image_url', 'options', 'fk_event']

class UserQuestionGetSerializer(serializers.ModelSerializer):
    fk_question = QuestionSerializer()

    class Meta: 
        model = User_Question
        fields = ['id', 'fk_question', 'answer','review_status']


class UserQuestionAnswerUpdateSerializer(serializers.Serializer):  # ponytail: explicit reject, minimal fields
    answer = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=3)
    review_status = serializers.BooleanField(required=False)

    def validate(self, attrs):
        allowed = {"answer", "review_status"}
        unknown = set(self.initial_data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError({k: "Unknown field." for k in unknown})
        if not attrs:
            raise serializers.ValidationError("At least one of answer or review_status is required.")
        return attrs


class UserQuestionAnswerResponseSerializer(serializers.ModelSerializer):
    question_id = serializers.UUIDField(source="fk_question.id", read_only=True)

    class Meta:
        model = User_Question
        fields = ['id', 'question_id', 'answer', 'review_status', 'updated_at']
        read_only_fields = fields


# ponytail: keep legacy name as wrapper alias
class UserQuestionAnswerSerializer(UserQuestionAnswerUpdateSerializer):
    pass
