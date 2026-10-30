from django import forms
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.db import transaction
from datetime import date, datetime, time, timedelta
from django.utils import timezone
from .models import Enrollment, Lecture, Section, Student, WorkItem


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "textarea" if isinstance(field.widget, forms.Textarea) else "input"
            field.widget.attrs.setdefault("class", f"field {css}")


class SectionForm(StyledModelForm):
    class Meta:
        model = Section
        fields = ["name"]


class StudentForm(StyledModelForm):
    password = forms.CharField(
        label="Initial password" , required=False,
        widget=forms.PasswordInput(attrs={"class": "field input", "autocomplete": "new-password"}),
        help_text="Required for a new student. It is saved as a one-way hash and can never be viewed later.",
    )

    class Meta:
        model = Student
        fields = ["email", "full_name", "academic_number", "section", "major"]
        widgets = {"full_name": forms.TextInput(), "major": forms.TextInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["password"].required = True

    def save(self, commit=True):
        student = super().save(commit=False)
        raw_password = self.cleaned_data.get("password")
        if raw_password:
            student.password = make_password(raw_password)
        if commit:
            student.save()
            self.save_m2m()
        return student


class StudentImportForm(forms.Form):
    file = forms.FileField(
        label="Excel workbook",
        widget=forms.ClearableFileInput(attrs={"class": "field input", "accept": ".xlsx"}),
    )
    update_existing = forms.BooleanField(
        label="Update matching students and reset their password hashes from this workbook",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "import-checkbox"}),
        help_text="Matches by email and university number. Existing student records and their related data are kept.",
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        if not uploaded_file.name.lower().endswith(".xlsx"):
            raise ValidationError("Upload an Excel workbook with the .xlsx extension.")
        if uploaded_file.size > 5 * 1024 * 1024:
            raise ValidationError("The workbook must be 5 MB or smaller.")
        return uploaded_file


class AttendanceReportForm(forms.Form):
    date = forms.DateField(
        label="Report date",
        widget=forms.DateInput(attrs={"type": "date", "class": "field input"}),
    )


class SectionCalendarFilterForm(forms.Form):
    section = forms.ModelChoiceField(
        queryset=Section.objects.order_by("name"),
        required=False,
        empty_label="All sections",
        widget=forms.Select(attrs={"class": "field input"}),
    )
    month = forms.DateField(
        label="Month",
        input_formats=["%Y-%m"],
        widget=forms.DateInput(
            attrs={"type": "month", "class": "field input"},
            format="%Y-%m",
        ),
    )


class LectureListFilterForm(forms.Form):
    section = forms.ModelChoiceField(
        queryset=Section.objects.order_by("name"),
        required=False,
        empty_label="All sections",
        widget=forms.Select(attrs={"class": "field input"}),
    )
    weekday = forms.TypedChoiceField(
        choices=[("", "All days"), *Lecture.Weekday.choices],
        coerce=int,
        empty_value=None,
        required=False,
        widget=forms.Select(attrs={"class": "field input"}),
    )


class LectureForm(forms.Form):
    section = forms.ModelChoiceField(
        queryset=Section.objects.all(),
        empty_label="Choose a section",
        widget=forms.Select(attrs={"class": "field input"}),
    )
    weekday = forms.TypedChoiceField(
        label="Weekday",
        choices=[("", "Choose a weekday"), *Lecture.Weekday.choices],
        coerce=int,
        empty_value=None,
        widget=forms.Select(attrs={"class": "field input"}),
    )
    first_subject = forms.CharField(
        label="4:00 PM - 7:00 PM subject",
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={"class": "field input", "placeholder": "Leave blank if there is no lecture"}),
    )
    second_subject = forms.CharField(
        label="7:00 PM - 10:00 PM subject",
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={"class": "field input", "placeholder": "Leave blank if there is no lecture"}),
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        if instance is not None and instance.weekday is not None:
            self.initial.setdefault("section", instance.section_id)
            self.initial.setdefault("weekday", instance.weekday)
        section_id = self.data.get("section") if self.data.get("section") else self.initial.get("section")
        weekday = self.data.get("weekday")
        if weekday in (None, ""):
            weekday = self.initial.get("weekday")
        if section_id and weekday is not None:
            scheduled = Lecture.objects.filter(section_id=section_id, weekday=weekday, slot__isnull=False)
            for lecture in scheduled:
                field_name = "first_subject" if lecture.slot == Lecture.Slot.AFTERNOON else "second_subject"
                if field_name not in self.data:
                    self.initial[field_name] = lecture.title

    @staticmethod
    def _slot_datetimes(weekday, slot):
        today = timezone.localdate()
        lecture_date = today + timedelta(days=(weekday - today.weekday()) % 7)
        start_hour = 16 if slot == Lecture.Slot.AFTERNOON else 19
        end_hour = start_hour + 3
        start = datetime.combine(lecture_date, time(start_hour))
        end = datetime.combine(lecture_date, time(end_hour))
        if timezone.is_aware(timezone.now()):
            start = timezone.make_aware(start, timezone.get_current_timezone())
            end = timezone.make_aware(end, timezone.get_current_timezone())
        return start, end

    def save(self):
        section = self.cleaned_data["section"]
        weekday = self.cleaned_data["weekday"]
        subjects_by_slot = {
            Lecture.Slot.AFTERNOON: self.cleaned_data["first_subject"].strip(),
            Lecture.Slot.EVENING: self.cleaned_data["second_subject"].strip(),
        }
        saved = []

        with transaction.atomic():
            for slot, subject in subjects_by_slot.items():
                lecture = Lecture.objects.filter(
                    section=section,
                    weekday=weekday,
                    slot=slot,
                ).first()
                if not subject:
                    if lecture:
                        lecture.delete()
                    continue

                scheduled_start, scheduled_end = self._slot_datetimes(weekday, slot)
                if lecture is None:
                    lecture = Lecture(section=section, weekday=weekday, slot=slot)
                lecture.title = subject
                lecture.location = ""
                lecture.scheduled_start = scheduled_start
                lecture.scheduled_end = scheduled_end
                lecture.full_clean()
                lecture.save()
                saved.append(lecture)
        return saved


class EnrollmentForm(forms.Form):
    student = forms.ModelChoiceField(queryset=Student.objects.none(), widget=forms.Select(attrs={"class": "field input"}))

    def __init__(self, *args, lecture, **kwargs):
        self.lecture = lecture
        super().__init__(*args, **kwargs)
        self.fields["student"].queryset = Student.objects.filter(section=lecture.section).order_by("academic_number")

    def clean_student(self):
        student = self.cleaned_data["student"]
        if student.enrollments.filter(lecture=self.lecture).exists():
            raise ValidationError("This student is already assigned to this lecture.")
        return student

    def save(self):
        return Enrollment.objects.create(student=self.cleaned_data["student"], lecture=self.lecture)


class WorkItemForm(StyledModelForm):
    class Meta:
        model = WorkItem
        fields = ["section", "lecture", "kind", "title", "description", "starts_at", "due_at"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("starts_at", "due_at"):
            self.fields[name].input_formats = ["%Y-%m-%dT%H:%M"]
        section_id = self.data.get("section") or getattr(self.instance, "section_id", None)
        if section_id:
            self.fields["lecture"].queryset = Lecture.objects.filter(section_id=section_id)
        else:
            self.fields["lecture"].queryset = Lecture.objects.none()
        self.fields["lecture"].required = False
