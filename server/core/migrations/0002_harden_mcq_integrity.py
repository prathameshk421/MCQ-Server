from django.db import migrations, models
import django.db.models.deletion
import django.db.models.expressions


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='event',
            old_name='ems_event_id',
            new_name='external_event_id',
        ),
        migrations.RenameField(
            model_name='event',
            old_name='ems_slot_id',
            new_name='external_slot_id',
        ),
        migrations.AlterField(
            model_name='event',
            name='external_slot_id',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name='user_event',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddConstraint(
            model_name='event',
            constraint=models.CheckConstraint(
                check=models.Q(('end_time__gt', django.db.models.expressions.F('start_time'))),
                name='event_end_after_start',
            ),
        ),
        migrations.AddConstraint(
            model_name='event',
            constraint=models.UniqueConstraint(
                condition=models.Q(('external_slot_id__isnull', False)),
                fields=('external_slot_id',),
                name='unique_external_slot_id',
            ),
        ),
        migrations.AddConstraint(
            model_name='question',
            constraint=models.CheckConstraint(
                check=models.Q(('correct_option__gte', 0), ('correct_option__lt', 4)),
                name='question_correct_option_in_range',
            ),
        ),
        migrations.AddConstraint(
            model_name='user_question',
            constraint=models.UniqueConstraint(fields=('fk_user', 'fk_question'), name='unique_user_question'),
        ),
        migrations.AddConstraint(
            model_name='user_question',
            constraint=models.CheckConstraint(
                check=models.Q(('answer__isnull', True), _connector='OR') | models.Q(('answer__gte', 0), ('answer__lt', 4)),
                name='user_answer_in_range',
            ),
        ),
        migrations.AddConstraint(
            model_name='user_event',
            constraint=models.UniqueConstraint(fields=('fk_user', 'fk_event'), name='unique_user_event'),
        ),
        migrations.AddConstraint(
            model_name='user_result',
            constraint=models.UniqueConstraint(fields=('fk_user_event',), name='unique_result_per_user_event'),
        ),
        migrations.AddIndex(
            model_name='event',
            index=models.Index(fields=['start_time', 'end_time'], name='core_event_start_t_315f28_idx'),
        ),
        migrations.AddIndex(
            model_name='question',
            index=models.Index(fields=['fk_event', 'created_at'], name='core_questi_fk_even_750586_idx'),
        ),
        migrations.AddIndex(
            model_name='user_question',
            index=models.Index(fields=['fk_user', 'fk_question'], name='core_user_q_fk_user_f2b097_idx'),
        ),
        migrations.AddIndex(
            model_name='user_event',
            index=models.Index(fields=['fk_user', 'finished'], name='core_user_e_fk_user_6a7de0_idx'),
        ),
    ]
