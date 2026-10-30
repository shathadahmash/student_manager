from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password


class Section(models.Model):
    name = models.CharField(max_length=80, unique=True)
    group_number = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Student(models.Model):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=160, blank=True)
    academic_number = models.CharField(max_length=40, unique=True)
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name="students")
    major = models.CharField(max_length=120)
    password = models.CharField(max_length=128, help_text="Django password hash; never displayed.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["section__name", "academic_number"]

    def set_student_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_student_password(self, raw_password):
        return check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        previous_section_id = None
        if self.pk:
            previous_section_id = Student.objects.filter(pk=self.pk).values_list("section_id", flat=True).first()
        super().save(*args, **kwargs)
        if previous_section_id and previous_section_id != self.section_id:
            Enrollment.objects.filter(student=self).exclude(lecture__section_id=self.section_id).delete()
        weekly_lectures = Lecture.objects.filter(section_id=self.section_id, weekday__isnull=False)
        Enrollment.objects.bulk_create(
            [Enrollment(student=self, lecture=lecture) for lecture in weekly_lectures],
            ignore_conflicts=True,
        )

    def __str__(self):
        return f"{self.academic_number} — {self.email}"


class Lecture(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    class Slot(models.IntegerChoices):
        AFTERNOON = 1, "4:00 PM - 7:00 PM"
        EVENING = 2, "7:00 PM - 10:00 PM"

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="lectures")
    title = models.CharField(max_length=160)
    location = models.CharField(max_length=120, blank=True)
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices, null=True, blank=True)
    slot = models.PositiveSmallIntegerField(choices=Slot.choices, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_start", "title"]

    def clean(self):
        if self.scheduled_start and self.scheduled_end and self.scheduled_end <= self.scheduled_start:
            raise ValidationError({"scheduled_end": "End time must be after start time."})
        if self.weekday is not None and self.scheduled_start and self.scheduled_start.weekday() != self.weekday:
            raise ValidationError({"scheduled_start": "For a weekly lecture, choose a first date that matches the selected weekday."})
        if self.weekday is not None and self.slot is None:
            raise ValidationError({"slot": "Choose a time slot for a weekly lecture."})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.weekday is not None:
            Enrollment.objects.filter(lecture=self).exclude(student__section_id=self.section_id).delete()
            Enrollment.objects.bulk_create(
                [
                    Enrollment(student=student, lecture=self)
                    for student in Student.objects.filter(section_id=self.section_id).exclude(enrollments__lecture=self)
                ],
                ignore_conflicts=True,
            )

    def __str__(self):
        return f"{self.title} ({self.section})"


class Enrollment(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="enrollments")
    lecture = models.ForeignKey(Lecture, on_delete=models.CASCADE, related_name="enrollments")
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["student__academic_number", "lecture__scheduled_start"]
        constraints = [models.UniqueConstraint(fields=["student", "lecture"], name="unique_student_lecture")]

    def clean(self):
        if self.student_id and self.lecture_id:
            if self.student.section_id != self.lecture.section_id:
                raise ValidationError("Student and lecture must belong to the same section.")

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.completed and self.completed_at is None:
            self.completed_at = timezone.now()
        elif not self.completed:
            self.completed_at = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} — {self.lecture}"


class LectureAttendance(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="lecture_attendance")
    lecture = models.ForeignKey(Lecture, on_delete=models.CASCADE, related_name="attendance_records")
    attendance_date = models.DateField()
    present = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["lecture__scheduled_start", "student__academic_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "lecture", "attendance_date"],
                name="unique_student_lecture_attendance_day",
            )
        ]

    def clean(self):
        if self.student_id and self.lecture_id:
            if self.student.section_id != self.lecture.section_id:
                raise ValidationError("Student and lecture must belong to the same section.")
            if self.lecture.weekday is not None and self.lecture.weekday != self.attendance_date.weekday():
                raise ValidationError("Attendance date must match the weekly lecture day.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class WorkItem(models.Model):
    class Kind(models.TextChoices):
        HOMEWORK = "homework", "Homework"
        ASSIGNMENT = "assignment", "Assignment"
        EXAM = "exam", "Exam"
        OTHER = "other", "Other"

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="work_items")
    lecture = models.ForeignKey(Lecture, on_delete=models.SET_NULL, related_name="work_items", null=True, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.HOMEWORK)
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField(null=True, blank=True, help_text="Optional start time, useful for exams.")
    due_at = models.DateTimeField(help_text="Due date/time or exam end time.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_at", "title"]

    def clean(self):
        if self.lecture_id and self.section_id and self.lecture.section_id != self.section_id:
            raise ValidationError({"lecture": "Choose a lecture from the same section."})
        if self.starts_at and self.due_at and self.due_at <= self.starts_at:
            raise ValidationError({"due_at": "End/due time must be after the start time."})

    @property
    def is_overdue(self):
        return self.due_at < timezone.now()

    @property
    def reminder_due(self):
        now = timezone.now()
        return now <= self.due_at <= now + timezone.timedelta(hours=24)

    def __str__(self):
        return f"{self.get_kind_display()}: {self.title} ({self.section})"


class ExamAttendance(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="exam_attendance")
    exam = models.ForeignKey(WorkItem, on_delete=models.CASCADE, related_name="attendance_records")
    attendance_date = models.DateField()
    present = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["exam__starts_at", "student__academic_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "exam", "attendance_date"],
                name="unique_student_exam_attendance_day",
            )
        ]

    def clean(self):
        if self.exam_id and self.exam.kind != WorkItem.Kind.EXAM:
            raise ValidationError({"exam": "Attendance can only be recorded for exams."})
        if self.student_id and self.exam_id:
            if self.student.section_id != self.exam.section_id:
                raise ValidationError("Student and exam must belong to the same section.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class WorkItemCompletion(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="work_completions")
    work_item = models.ForeignKey(WorkItem, on_delete=models.CASCADE, related_name="completion_records")
    completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student__academic_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "work_item"],
                name="unique_student_work_item_completion",
            )
        ]

    def clean(self):
        if self.work_item_id and self.work_item.kind == WorkItem.Kind.EXAM:
            raise ValidationError({"work_item": "Exam completion is recorded through exam attendance."})
        if self.student_id and self.work_item_id:
            if self.student.section_id != self.work_item.section_id:
                raise ValidationError("Student and work item must belong to the same section.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
