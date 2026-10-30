import calendar as month_calendar
from datetime import date, datetime, time, timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.http import Http404
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.db.models.query import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from .forms import AttendanceReportForm, EnrollmentForm, LectureForm, LectureListFilterForm, SectionCalendarFilterForm, SectionForm, StudentForm, StudentImportForm, WorkItemForm
from .models import Enrollment, ExamAttendance, Lecture, LectureAttendance, Section, Student, WorkItem, WorkItemCompletion
from .student_import import import_students


class ManagerLoginView(LoginView):
    template_name = "manager/login.html"
    redirect_authenticated_user = True


@login_required
def dashboard(request):
    today = timezone.localdate()
    show_attended = request.GET.get("show_attended") == "1"
    now = timezone.now()
    day_start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
    day_end = day_start + timedelta(days=1)
    today_lecture_filter = (
        Q(weekday=today.weekday())
        | Q(weekday__isnull=True, scheduled_start__gte=day_start, scheduled_start__lt=day_end)
    )
    if request.method == "POST" and "mark_attendance" in request.POST:
        enrollment = get_object_or_404(
            Enrollment.objects.select_related("lecture"),
            pk=request.POST.get("enrollment_id"),
            lecture__in=Lecture.objects.filter(today_lecture_filter),
        )
        LectureAttendance.objects.update_or_create(
            student=enrollment.student,
            lecture=enrollment.lecture,
            attendance_date=today,
            defaults={"present": request.POST.get("present") == "on"},
        )
        if request.POST.get("show_attended") == "1":
            return redirect(f"{reverse('dashboard')}?show_attended=1")
        return redirect("dashboard")
    if request.method == "POST" and "mark_exam_attendance" in request.POST:
        exam = get_object_or_404(
            WorkItem,
            pk=request.POST.get("exam_id"),
            kind=WorkItem.Kind.EXAM,
        )
        exam_is_today = (
            exam.starts_at is not None
            and exam.starts_at < day_end
            and exam.due_at >= day_start
        ) or (
            exam.starts_at is None
            and day_start <= exam.due_at < day_end
        )
        if not exam_is_today:
            messages.error(request, "Exam attendance can only be updated on the exam date.")
            return redirect("dashboard")
        student = get_object_or_404(Student, pk=request.POST.get("student_id"), section_id=exam.section_id)
        ExamAttendance.objects.update_or_create(
            student=student,
            exam=exam,
            attendance_date=today,
            defaults={"present": request.POST.get("present") == "on"},
        )
        return redirect("dashboard")

    attendance_today = LectureAttendance.objects.filter(
        student_id=OuterRef("student_id"),
        lecture_id=OuterRef("lecture_id"),
        attendance_date=today,
        present=True,
    )
    enrollments_today = Enrollment.objects.select_related("student").annotate(
        attended_today=Exists(attendance_today)
    )
    if not show_attended:
        enrollments_today = enrollments_today.filter(attended_today=False)
    today_lectures = Lecture.objects.filter(today_lecture_filter).annotate(
        total_enrollments=Count("enrollments")
    ).select_related("section").prefetch_related(
        Prefetch("enrollments", queryset=enrollments_today)
    )
    today_exams = WorkItem.objects.filter(kind=WorkItem.Kind.EXAM).filter(
        Q(starts_at__lt=day_end, due_at__gte=day_start, starts_at__isnull=False)
        | Q(starts_at__isnull=True, due_at__gte=day_start, due_at__lt=day_end)
    ).select_related("section", "lecture").prefetch_related("section__students")
    today_exams = list(today_exams.prefetch_related(
        Prefetch(
            "attendance_records",
            queryset=ExamAttendance.objects.filter(attendance_date=today, present=True).select_related("student"),
        )
    ))
    for exam in today_exams:
        attended_student_ids = {record.student_id for record in exam.attendance_records.all()}
        exam.present_count = len(attended_student_ids)
        exam.student_roster = [
            {"student": student, "attended_today": student.pk in attended_student_ids}
            for student in exam.section.students.all()
        ]
    soon_items = WorkItem.objects.filter(due_at__gte=now, due_at__lte=now + timedelta(hours=24)).select_related("section", "lecture")
    overdue_items = WorkItem.objects.filter(due_at__lt=now).select_related("section", "lecture")[:8]
    return render(request, "manager/dashboard.html", {
        "today": today, "today_lectures": today_lectures, "today_exams": today_exams,
        "soon_items": soon_items, "show_attended": show_attended,
        "overdue_items": overdue_items, "student_count": Student.objects.count(),
        "lecture_count": Lecture.objects.count(), "section_count": Section.objects.count(),
    })


@login_required
def attendance_report(request):
    today = timezone.localdate()
    form = AttendanceReportForm(request.GET or None, initial={"date": today})
    report_date = today
    if request.GET and form.is_valid():
        report_date = form.cleaned_data["date"]

    day_start = timezone.make_aware(timezone.datetime.combine(report_date, timezone.datetime.min.time()))
    day_end = day_start + timedelta(days=1)
    lecture_filter = (
        Q(weekday=report_date.weekday())
        | Q(weekday__isnull=True, scheduled_start__gte=day_start, scheduled_start__lt=day_end)
    )
    attendance_for_enrollment = LectureAttendance.objects.filter(
        student_id=OuterRef("student_id"),
        lecture_id=OuterRef("lecture_id"),
        attendance_date=report_date,
        present=True,
    )
    roster = Enrollment.objects.select_related("student").annotate(
        attended_on_date=Exists(attendance_for_enrollment),
        attendance_checked_at=Subquery(attendance_for_enrollment.values("updated_at")[:1]),
    )
    lectures = Lecture.objects.filter(lecture_filter).select_related("section").prefetch_related(
        Prefetch("enrollments", queryset=roster)
    )
    exams = WorkItem.objects.filter(kind=WorkItem.Kind.EXAM).filter(
        Q(starts_at__lt=day_end, due_at__gte=day_start, starts_at__isnull=False)
        | Q(starts_at__isnull=True, due_at__gte=day_start, due_at__lt=day_end)
    ).select_related("section", "lecture").prefetch_related(
        "section__students",
        Prefetch(
            "attendance_records",
            queryset=ExamAttendance.objects.filter(attendance_date=report_date).select_related("student"),
        ),
    )
    totals = {"students": 0, "present": 0, "absent": 0, "lectures": 0, "exams": 0}
    for lecture in lectures:
        lecture.report_enrollments = list(lecture.enrollments.all())
        lecture.present_count = sum(enrollment.attended_on_date for enrollment in lecture.report_enrollments)
        lecture.absent_count = len(lecture.report_enrollments) - lecture.present_count
        totals["students"] += len(lecture.report_enrollments)
        totals["present"] += lecture.present_count
        totals["absent"] += lecture.absent_count
        totals["lectures"] += 1
    for exam in exams:
        attended_by_student = {
            record.student_id: record
            for record in exam.attendance_records.all()
            if record.present
        }
        exam.report_students = [
            {
                "student": student,
                "attended_on_date": student.pk in attended_by_student,
                "attendance_checked_at": (
                    attended_by_student[student.pk].updated_at if student.pk in attended_by_student else None
                ),
            }
            for student in exam.section.students.all()
        ]
        exam.present_count = sum(student["attended_on_date"] for student in exam.report_students)
        totals["students"] += len(exam.report_students)
        totals["present"] += exam.present_count
        totals["absent"] += len(exam.report_students) - exam.present_count
        totals["exams"] += 1

    return render(request, "manager/attendance_report.html", {
        "form": form,
        "report_date": report_date,
        "lectures": lectures,
        "exams": exams,
        "totals": totals,
    })


def _calendar_event_date(event_type, item):
    if event_type == "lecture":
        return timezone.localtime(item.scheduled_start).date()
    if item.kind == WorkItem.Kind.EXAM and item.starts_at:
        return timezone.localtime(item.starts_at).date()
    return timezone.localtime(item.due_at).date()


def _calendar_event_time(event_type, item):
    if event_type == "lecture":
        return timezone.localtime(item.scheduled_start)
    if item.kind == WorkItem.Kind.EXAM and item.starts_at:
        return timezone.localtime(item.starts_at)
    return timezone.localtime(item.due_at)


@login_required
def section_calendar(request):
    today = timezone.localdate()
    initial_month = today.replace(day=1)
    form = SectionCalendarFilterForm(
        request.GET or None,
        initial={"month": initial_month},
    )
    month_start = initial_month
    selected_section = None
    if request.GET and form.is_valid():
        month_start = form.cleaned_data["month"].replace(day=1)
        selected_section = form.cleaned_data["section"]
    elif not request.GET:
        form = SectionCalendarFilterForm(initial={"month": initial_month})

    month_days = month_calendar.Calendar(firstweekday=0).monthdatescalendar(
        month_start.year,
        month_start.month,
    )
    grid_start = month_days[0][0]
    grid_end = month_days[-1][-1] + timedelta(days=1)
    grid_start_dt = timezone.make_aware(datetime.combine(grid_start, time.min))
    grid_end_dt = timezone.make_aware(datetime.combine(grid_end, time.min))
    section_filter = {"pk": selected_section.pk} if selected_section else {}
    item_section_filter = {"section": selected_section} if selected_section else {}
    section_students = {
        section.pk: list(section.students.all())
        for section in Section.objects.filter(**section_filter).prefetch_related("students")
    }

    weekly_lectures = Lecture.objects.filter(
        weekday__isnull=False,
        **item_section_filter,
    ).select_related("section")
    one_time_lectures = Lecture.objects.filter(
        weekday__isnull=True,
        scheduled_start__gte=grid_start_dt,
        scheduled_start__lt=grid_end_dt,
        **item_section_filter,
    ).select_related("section")
    lectures = list(weekly_lectures) + list(one_time_lectures)

    work_items = list(
        WorkItem.objects.filter(
            Q(
                kind=WorkItem.Kind.EXAM,
                starts_at__isnull=False,
                starts_at__gte=grid_start_dt,
                starts_at__lt=grid_end_dt,
            )
            | Q(
                kind=WorkItem.Kind.EXAM,
                starts_at__isnull=True,
                due_at__gte=grid_start_dt,
                due_at__lt=grid_end_dt,
            )
            | Q(
                kind__in=[WorkItem.Kind.HOMEWORK, WorkItem.Kind.ASSIGNMENT, WorkItem.Kind.OTHER],
                due_at__gte=grid_start_dt,
                due_at__lt=grid_end_dt,
            ),
            **item_section_filter,
        ).select_related("section", "lecture")
    )
    lecture_ids = [lecture.pk for lecture in lectures]
    exam_ids = [item.pk for item in work_items if item.kind == WorkItem.Kind.EXAM]
    work_ids = [item.pk for item in work_items if item.kind != WorkItem.Kind.EXAM]
    lecture_done = set(
        LectureAttendance.objects.filter(
            lecture_id__in=lecture_ids,
            attendance_date__gte=grid_start,
            attendance_date__lt=grid_end,
            present=True,
        ).values_list("lecture_id", "attendance_date", "student_id")
    )
    exam_done = set(
        ExamAttendance.objects.filter(
            exam_id__in=exam_ids,
            attendance_date__gte=grid_start,
            attendance_date__lt=grid_end,
            present=True,
        ).values_list("exam_id", "attendance_date", "student_id")
    )
    work_done = set(
        WorkItemCompletion.objects.filter(
            work_item_id__in=work_ids,
            completed=True,
        ).values_list("work_item_id", "student_id")
    )
    events_by_date = {}
    now = timezone.now()

    def add_event(event_type, item, event_date, event_time):
        students = section_students.get(item.section_id, [])
        if event_type == "lecture":
            done_count = sum(
                (item.pk, event_date, student.pk) in lecture_done
                for student in students
            )
            started_at = event_time
        elif item.kind == WorkItem.Kind.EXAM:
            done_count = sum(
                (item.pk, event_date, student.pk) in exam_done
                for student in students
            )
            started_at = timezone.localtime(item.starts_at) if item.starts_at else None
        else:
            done_count = sum((item.pk, student.pk) in work_done for student in students)
            started_at = None
        complete = bool(students) and done_count == len(students)
        if complete:
            status = "complete"
        elif event_type == "lecture" and started_at <= now:
            status = "incomplete"
        elif event_type == "work":
            status = "incomplete"
        else:
            status = "upcoming"
        events_by_date.setdefault(event_date, []).append({
            "event_type": event_type,
            "event_id": item.pk,
            "date": event_date,
            "title": item.title,
            "kind": item.kind if event_type == "work" else "lecture",
            "section_name": item.section.name,
            "time_label": event_time.strftime("%I:%M %p").lstrip("0"),
            "sort_time": event_time.strftime("%H:%M"),
            "status": status,
            "done_count": done_count,
            "total_count": len(students),
        })

    for lecture in lectures:
        if lecture.weekday is not None:
            lecture_time = timezone.localtime(lecture.scheduled_start).time()
            event_date = grid_start
            while event_date < grid_end:
                if event_date.weekday() == lecture.weekday:
                    event_time = timezone.make_aware(
                        datetime.combine(event_date, lecture_time),
                        timezone.get_current_timezone(),
                    )
                    add_event("lecture", lecture, event_date, event_time)
                event_date += timedelta(days=1)
        else:
            event_time = timezone.localtime(lecture.scheduled_start)
            add_event("lecture", lecture, event_time.date(), event_time)

    for item in work_items:
        event_type = "work"
        event_time = _calendar_event_time(event_type, item)
        add_event(event_type, item, event_time.date(), event_time)

    weeks = [
        [
            {
                "date": day,
                "in_month": day.month == month_start.month,
                "is_today": day == today,
                "events": sorted(
                    events_by_date.get(day, []),
                    key=lambda event: event["sort_time"],
                ),
            }
            for day in week
        ]
        for week in month_days
    ]
    previous_month = (month_start - timedelta(days=1)).replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return render(request, "manager/section_calendar.html", {
        "form": form,
        "weeks": weeks,
        "month_start": month_start,
        "previous_month": previous_month,
        "next_month": next_month,
        "selected_section": selected_section,
        "today": today,
    })


@login_required
def calendar_event(request, event_type, event_id, event_date):
    try:
        selected_date = date.fromisoformat(event_date)
    except ValueError:
        raise Http404("Invalid calendar event date.")

    if event_type == "lecture":
        item = get_object_or_404(Lecture.objects.select_related("section"), pk=event_id)
        valid_date = (
            item.weekday == selected_date.weekday()
            if item.weekday is not None
            else timezone.localtime(item.scheduled_start).date() == selected_date
        )
        if not valid_date:
            raise Http404("This lecture is not scheduled on that date.")
        roster = list(item.section.students.order_by("academic_number"))
        records = {
            record.student_id: record
            for record in LectureAttendance.objects.filter(
                lecture=item,
                attendance_date=selected_date,
            )
        }
        event_title = item.title
        event_kind = "Lecture"
    else:
        item = get_object_or_404(WorkItem.objects.select_related("section"), pk=event_id)
        if event_type != "work" or _calendar_event_date("work", item) != selected_date:
            raise Http404("This work item is not scheduled on that date.")
        roster = list(item.section.students.order_by("academic_number"))
        if item.kind == WorkItem.Kind.EXAM:
            records = {
                record.student_id: record
                for record in ExamAttendance.objects.filter(
                    exam=item,
                    attendance_date=selected_date,
                )
            }
        else:
            records = {
                record.student_id: record
                for record in WorkItemCompletion.objects.filter(work_item=item)
            }
        event_title = item.title
        event_kind = item.get_kind_display()

    if request.method == "POST":
        student = get_object_or_404(Student, pk=request.POST.get("student_id"), section=item.section)
        completed = request.POST.get("completed") == "on"
        if event_type == "lecture":
            LectureAttendance.objects.update_or_create(
                student=student,
                lecture=item,
                attendance_date=selected_date,
                defaults={"present": completed},
            )
        elif item.kind == WorkItem.Kind.EXAM:
            ExamAttendance.objects.update_or_create(
                student=student,
                exam=item,
                attendance_date=selected_date,
                defaults={"present": completed},
            )
        else:
            WorkItemCompletion.objects.update_or_create(
                student=student,
                work_item=item,
                defaults={"completed": completed},
            )
        return redirect("calendar_event", event_type=event_type, event_id=item.pk, event_date=selected_date.isoformat())

    student_rows = []
    for student in roster:
        record = records.get(student.pk)
        completed = record.present if record and (event_type == "lecture" or item.kind == WorkItem.Kind.EXAM) else (
            record.completed if record else False
        )
        student_rows.append({"student": student, "completed": completed})
    return render(request, "manager/calendar_event.html", {
        "event_title": event_title,
        "event_kind": event_kind,
        "event_date": selected_date,
        "students": student_rows,
        "month": selected_date.strftime("%Y-%m"),
        "section_id": item.section_id,
        "today": timezone.localdate(),
    })


@login_required
def section_list(request):
    form = SectionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Section added.")
        return redirect("sections")
    return render(request, "manager/sections.html", {"form": form, "sections": Section.objects.all()})


@login_required
def student_list(request):
    students = Student.objects.select_related("section").all()
    query = request.GET.get("q", "").strip()
    if query:
        students = students.filter(Q(email__icontains=query) | Q(full_name__icontains=query) | Q(academic_number__icontains=query) | Q(major__icontains=query) | Q(section__name__icontains=query))
    return render(request, "manager/student_list.html", {"students": students, "query": query})


@login_required
def student_create(request):
    form = StudentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Student added. The password is stored securely and cannot be retrieved.")
        return redirect("students")
    return render(request, "manager/student_form.html", {"form": form, "title": "Add student"})


@login_required
def student_import(request):
    form = StudentImportForm(request.POST or None, request.FILES or None)
    imported = None
    updated = 0
    issues = []
    if request.method == "POST" and form.is_valid():
        try:
            imported, updated, issues = import_students(
                form.cleaned_data["file"],
                update_existing=form.cleaned_data["update_existing"],
            )
        except ValidationError as error:
            form.add_error("file", error)
    return render(request, "manager/student_import.html", {
        "form": form,
        "imported": imported,
        "updated": updated,
        "issues": issues,
        "issue_count": len(issues),
    })


@login_required
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)
    form = StudentForm(request.POST or None, instance=student)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Student details updated.")
        return redirect("students")
    return render(request, "manager/student_form.html", {"form": form, "title": "Edit student", "student": student})


@login_required
def student_delete(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if request.method == "POST":
        student.delete()
        messages.success(request, "Student deleted.")
        return redirect("students")
    return render(request, "manager/confirm_delete.html", {"object": student, "kind": "student", "cancel_url": "students"})


@login_required
def lecture_list(request):
    form = LectureListFilterForm(request.GET or None)
    lectures = Lecture.objects.select_related("section").prefetch_related("enrollments")
    if form.is_valid():
        section = form.cleaned_data["section"]
        weekday = form.cleaned_data["weekday"]
        if section:
            lectures = lectures.filter(section=section)
        if weekday is not None:
            django_weekday = (weekday + 1) % 7 + 1
            lectures = lectures.filter(
                Q(weekday=weekday)
                | Q(weekday__isnull=True, scheduled_start__week_day=django_weekday)
            )
    return render(request, "manager/lecture_list.html", {
        "lectures": lectures,
        "filter_form": form,
    })


@login_required
def lecture_create(request):
    form = LectureForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lectures = form.save()
        messages.success(request, f"Weekly schedule saved. {len(lectures)} subject(s) scheduled; blank time slots are cleared.")
        return redirect("lectures")
    return render(request, "manager/lecture_form.html", {"form": form, "title": "Add lecture"})


@login_required
def lecture_edit(request, pk):
    lecture = get_object_or_404(Lecture, pk=pk)
    form = LectureForm(request.POST or None, instance=lecture)
    if request.method == "POST" and form.is_valid():
        lectures = form.save()
        messages.success(request, f"Weekly schedule saved. {len(lectures)} subject(s) scheduled; blank time slots are cleared.")
        return redirect("lectures")
    return render(request, "manager/lecture_form.html", {"form": form, "title": "Edit lecture"})


@login_required
def lecture_delete(request, pk):
    lecture = get_object_or_404(Lecture, pk=pk)
    if request.method == "POST":
        lecture.delete()
        messages.success(request, "Lecture deleted.")
        return redirect("lectures")
    return render(request, "manager/confirm_delete.html", {"object": lecture, "kind": "lecture", "cancel_url": "lectures"})


@login_required
def lecture_detail(request, pk):
    lecture = get_object_or_404(Lecture.objects.select_related("section"), pk=pk)
    form = EnrollmentForm(request.POST or None, lecture=lecture)
    if request.method == "POST" and lecture.weekday is not None:
        messages.error(request, "Weekly lecture rosters are managed automatically for the whole section.")
        return redirect("lecture_detail", pk=lecture.pk)
    if request.method == "POST" and "assign" in request.POST:
        if form.is_valid():
            form.save()
            messages.success(request, "Student assigned to the lecture.")
            return redirect("lecture_detail", pk=lecture.pk)
    if request.method == "POST" and "toggle_completion" in request.POST:
        enrollment = get_object_or_404(Enrollment, pk=request.POST.get("enrollment_id"), lecture=lecture)
        enrollment.completed = not enrollment.completed
        enrollment.save()
        messages.success(request, "Lecture completion updated.")
        return redirect("lecture_detail", pk=lecture.pk)
    if request.method == "POST" and "remove_enrollment" in request.POST:
        enrollment = get_object_or_404(Enrollment, pk=request.POST.get("enrollment_id"), lecture=lecture)
        enrollment.delete()
        messages.success(request, "Student removed from this lecture.")
        return redirect("lecture_detail", pk=lecture.pk)
    return render(request, "manager/lecture_detail.html", {"lecture": lecture, "form": form, "enrollments": lecture.enrollments.select_related("student")})


@login_required
def work_list(request):
    return render(request, "manager/work_list.html", {"items": WorkItem.objects.select_related("section", "lecture")})


@login_required
def work_create(request):
    form = WorkItemForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Work item added. It is automatically shared with students in the selected section.")
        return redirect("work_items")
    return render(request, "manager/work_form.html", {"form": form, "title": "Add homework, assignment or exam"})


@login_required
def work_edit(request, pk):
    item = get_object_or_404(WorkItem, pk=pk)
    form = WorkItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Work item updated for the section.")
        return redirect("work_items")
    return render(request, "manager/work_form.html", {"form": form, "title": "Edit work item"})


@login_required
def work_delete(request, pk):
    item = get_object_or_404(WorkItem, pk=pk)
    if request.method == "POST":
        item.delete()
        messages.success(request, "Work item deleted for the section.")
        return redirect("work_items")
    return render(request, "manager/confirm_delete.html", {"object": item, "kind": "work item", "cancel_url": "work_items"})
