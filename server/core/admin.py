import csv
import hashlib
import io

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models, transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import path
from martor.widgets import AdminMartorWidget
from csvexport.actions import csvexport

from .models import Event, Question, QuestionImportAudit, User, User_Event, User_Question, User_Result


CSV_HEADERS = [
    'question_id', 'statement', 'option_1', 'option_2', 'option_3', 'option_4',
    'correct_option', 'code', 'image_url',
]


class QuestionCsvUploadForm(forms.Form):
    event = forms.ModelChoiceField(queryset=Event.objects.all(), help_text='Event for import')
    csv_upload = forms.FileField(help_text='UTF-8/UTF-8-BOM CSV, max 5 MiB, using exact template headers.')

    def clean_csv_upload(self):
        f = self.cleaned_data['csv_upload']
        if f.size > 5 * 1024 * 1024:
            raise ValidationError('File too large, max 5 MiB.')
        return f


class QuestionAdminForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        options = cleaned_data.get('options')
        correct_option = cleaned_data.get('correct_option')
        if options and len(options) != 4:
            self.add_error('options', 'Exactly four options are required.')
        if correct_option is not None and not 0 <= correct_option < 4:
            self.add_error('correct_option', 'Use a zero-based option index between 0 and 3.')
        return cleaned_data


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    change_list_template = 'change_list.html'  # ponytail: keep minimal template
    form = QuestionAdminForm
    list_display = ('id', 'statement', 'fk_event', 'correct_option', 'updated_at')
    list_filter = ('fk_event',)
    search_fields = ('statement',)

    def get_urls(self):
        urls = super().get_urls()
        return [
            path('import-csv/', self.admin_site.admin_view(self.import_csv), name='core_question_import_csv'),
            path('export-csv/', self.admin_site.admin_view(self.export_csv), name='core_question_export_csv'),
        ] + urls

    def import_csv(self, request):
        if not (request.user.has_perm('core.add_question') and request.user.has_perm('core.change_question')):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        form = QuestionCsvUploadForm(request.POST or None, request.FILES or None)
        if request.method == 'POST' and form.is_valid():
            event = form.cleaned_data['event']
            f = form.cleaned_data['csv_upload']
            raw = f.read()
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError as e:
                form.add_error('csv_upload', str(e))
                return render(request, 'csv_upload.html', {'form': form, 'title': 'Import MCQ questions from CSV'})
            sha = hashlib.sha256(raw).hexdigest()
            # strict header check
            reader = csv.DictReader(io.StringIO(text))
            if reader.fieldnames != CSV_HEADERS:
                form.add_error('csv_upload', 'Headers must be exactly: %s' % ','.join(CSV_HEADERS))
                return render(request, 'csv_upload.html', {'form': form, 'title': 'Import MCQ questions from CSV'})
            if len(reader.fieldnames) != len(set(reader.fieldnames)):
                form.add_error('csv_upload', 'Duplicate headers.')
                return render(request, 'csv_upload.html', {'form': form, 'title': 'Import MCQ questions from CSV'})
            rows = list(reader)
            # validate all in memory
            seen_ids = set()
            errors = []
            to_create = []
            to_update = []
            url_validator = URLValidator()
            for idx, row in enumerate(rows, start=2):
                try:
                    qid_raw = (row.get('question_id') or '').strip()
                    if qid_raw:
                        if qid_raw in seen_ids:
                            raise ValueError('duplicate question_id in file')
                        seen_ids.add(qid_raw)
                        try:
                            qobj = Question.objects.get(id=qid_raw)
                            if str(qobj.fk_event_id) != str(event.id):
                                raise ValueError('question_id not in selected event')
                        except Question.DoesNotExist:
                            raise ValueError('question_id not found')
                        # will update
                    statement = (row.get('statement') or '').strip()
                    opts = [(row.get('option_1') or '').strip(), (row.get('option_2') or '').strip(), (row.get('option_3') or '').strip(), (row.get('option_4') or '').strip()]
                    if not statement or any(not o for o in opts):
                        raise ValueError('statement/options required trimmed non-empty')
                    try:
                        correct = int((row.get('correct_option') or '').strip())
                    except:
                        raise ValueError('correct_option must be 0..3')
                    if not 0 <= correct <= 3:
                        raise ValueError('correct_option must be 0..3')
                    code = (row.get('code') or '').strip() or None
                    image_url = (row.get('image_url') or '').strip() or None
                    if image_url:
                        url_validator(image_url)
                    # validate via full_clean
                    if qid_raw:
                        q = Question.objects.get(id=qid_raw)
                        q.statement = statement
                        q.options = opts
                        q.correct_option = correct
                        q.code = code
                        q.image_url = image_url
                        q.fk_event = event
                    else:
                        q = Question(statement=statement, options=opts, correct_option=correct, code=code, image_url=image_url, fk_event=event)
                    q.full_clean()
                    if qid_raw:
                        to_update.append(q)
                    else:
                        to_create.append(q)
                except Exception as e:
                    # ponytail: collect all errors, write nothing if any
                    errors.append('Row %s: %s' % (idx, e))
            if errors:
                for e in errors:
                    form.add_error('csv_upload', e)
                return render(request, 'csv_upload.html', {'form': form, 'title': 'Import MCQ questions from CSV'})
            # atomic write
            created = updated = 0
            with transaction.atomic():
                for q in to_create:
                    q.save()
                    created += 1
                for q in to_update:
                    q.save()
                    updated += 1
            # audit after commit
            QuestionImportAudit.objects.create(fk_event=event, actor=request.user, filename=f.name, sha256=sha, created_count=created, updated_count=updated)
            self.message_user(request, 'Event %s: %s created, %s updated.' % (event.id, created, updated), messages.SUCCESS)
            return redirect('admin:core_question_changelist')
        return render(request, 'csv_upload.html', {'form': form, 'title': 'Import MCQ questions from CSV'})

    # keep legacy names for template compatibility
    def upload_csv(self, request):
        return self.import_csv(request)

    def csv_template(self, request):
        return self.export_csv(request)

    def export_csv(self, request):
        if not request.user.has_perm('core.view_question'):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        event_id = request.GET.get('event_id')
        if not event_id:
            # ponytail: require event_id param
            return HttpResponse('event_id query param required', status=400)
        try:
            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return HttpResponse('event not found', status=404)
        qs = Question.objects.filter(fk_event=event).order_by('created_at')
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="mcq-questions-%s.csv"' % event.id
        writer = csv.DictWriter(response, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for q in qs:
            writer.writerow({
                'question_id': str(q.id),
                'statement': q.statement,
                'option_1': q.options[0], 'option_2': q.options[1], 'option_3': q.options[2], 'option_4': q.options[3],
                'correct_option': q.correct_option,
                'code': q.code or '', 'image_url': q.image_url or '',
            })
        return response

    formfield_overrides = {models.TextField: {'widget': AdminMartorWidget}}


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = (*UserAdmin.fieldsets, ('Custom Fields', {'fields': ('current_user_event',)}))


@admin.register(Event)
class CustomEventAdmin(admin.ModelAdmin):
    list_display = ('name', 'external_event_id', 'external_slot_id', 'start_time', 'end_time')
    search_fields = ('name', 'external_event_id', 'external_slot_id')
    list_filter = ('start_time', 'end_time')


@admin.register(User_Event)
class CustomUserEventAdmin(admin.ModelAdmin):
    list_display = ('fk_user', 'fk_event', 'started', 'finished')
    search_fields = ('fk_user__username', 'fk_event__name')
    list_filter = ('started', 'finished')


@admin.register(User_Result)
class CustomUserResult(admin.ModelAdmin):
    list_display = ('event', 'score')
    actions = [csvexport]

    def event(self, obj):
        return obj.fk_user_event.fk_event.name


admin.site.register(User_Question)
