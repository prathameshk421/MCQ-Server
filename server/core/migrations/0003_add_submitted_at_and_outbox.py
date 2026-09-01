# Generated for ponytail minimal outbox + submitted_at
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_harden_mcq_integrity'),
    ]

    operations = [
        migrations.AddField(
            model_name='user_event',
            name='submitted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='question',
            constraint=models.CheckConstraint(check=models.Q(('options__len', 4)), name='question_options_length_is_four'),
        ),
        migrations.CreateModel(
            name='ScoreDispatch',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('pending', 'pending'), ('queued', 'queued'), ('completed', 'completed'), ('failed', 'failed')], default='pending', max_length=10)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('last_error', models.TextField(blank=True, null=True)),
                ('queued_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('fk_user_event', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='score_dispatch', to='core.user_event')),
            ],
        ),
        migrations.AddIndex(
            model_name='scoredispatch',
            index=models.Index(fields=['status', 'updated_at'], name='core_scored_status_8a1d2f_idx'),
        ),
        migrations.CreateModel(
            name='QuestionImportAudit',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('filename', models.CharField(max_length=255)),
                ('sha256', models.CharField(max_length=64)),
                ('created_count', models.PositiveIntegerField(default=0)),
                ('updated_count', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('fk_event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.event')),
            ],
        ),
    ]
