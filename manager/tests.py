from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ExamAttendance, Lecture, Section, Student, WorkItem


class ExamAttendanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="manager", password="test-password")
        self.client.force_login(self.user)
        self.section = Section.objects.create(name="Section A")
        self.student = Student.objects.create(
            email="student@example.com",
            full_name="Test Student",
            academic_number="1001",
            section=self.section,
            major="Science",
            password="hashed-password",
        )
        self.today = timezone.localdate()
        self.today_exam = self.create_exam("Exam today", self.today)
        self.tomorrow = self.today + timedelta(days=1)
        self.tomorrow_exam = self.create_exam("Exam tomorrow", self.tomorrow)

    def create_exam(self, title, exam_date):
        due_at = timezone.make_aware(datetime.combine(exam_date, time(18)))
        return WorkItem.objects.create(
            section=self.section,
            kind=WorkItem.Kind.EXAM,
            title=title,
            due_at=due_at,
        )

    def test_dashboard_marks_exam_attendance_for_one_student(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'name="mark_exam_attendance"')

        response = self.client.post(reverse("dashboard"), {
            "mark_exam_attendance": "1",
            "exam_id": self.today_exam.pk,
            "student_id": self.student.pk,
            "present": "on",
        })

        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(ExamAttendance.objects.get(exam=self.today_exam, student=self.student).present)
        self.assertContains(self.client.get(reverse("dashboard")), "checked")

    def test_attendance_report_filters_exams_by_selected_day(self):
        response = self.client.get(reverse("attendance_report"), {"date": self.tomorrow.isoformat()})

        self.assertContains(response, self.tomorrow_exam.title)
        self.assertNotContains(response, self.today_exam.title)
        self.assertEqual(response.context["totals"]["exams"], 1)


class SectionCalendarTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="calendar-manager", password="test-password")
        self.client.force_login(user)
        self.section = Section.objects.create(name="Calendar section")
        self.students = [
            Student.objects.create(
                email=f"calendar-{number}@example.com",
                full_name=f"Student {number}",
                academic_number=f"200{number}",
                section=self.section,
                major="Science",
                password="hashed-password",
            )
            for number in (1, 2)
        ]
        self.other_section = Section.objects.create(name="Other section")
        self.other_student = Student.objects.create(
            email="other@example.com",
            full_name="Other Student",
            academic_number="3001",
            section=self.other_section,
            major="Science",
            password="hashed-password",
        )

    def test_calendar_filters_by_section_and_colors_work_after_every_student_is_done(self):
        event_date = timezone.localdate() + timedelta(days=1)
        due_at = timezone.make_aware(datetime.combine(event_date, time(18)))
        assignment = WorkItem.objects.create(
            section=self.section,
            kind=WorkItem.Kind.ASSIGNMENT,
            title="Section assignment",
            due_at=due_at,
        )
        WorkItem.objects.create(
            section=self.other_section,
            kind=WorkItem.Kind.ASSIGNMENT,
            title="Other section assignment",
            due_at=due_at,
        )
        event_url = reverse(
            "calendar_event",
            args=["work", assignment.pk, event_date.isoformat()],
        )
        self.client.post(event_url, {"student_id": self.students[0].pk, "completed": "on"})

        calendar_url = reverse("section_calendar")
        query = {"month": event_date.strftime("%Y-%m"), "section": self.section.pk}
        response = self.client.get(calendar_url, query)
        self.assertContains(response, "Section assignment")
        self.assertNotContains(response, "Other section assignment")
        self.assertContains(response, "1/2 done")
        self.assertContains(response, "calendar-event incomplete assignment")

        self.client.post(event_url, {"student_id": self.students[1].pk, "completed": "on"})
        response = self.client.get(calendar_url, query)
        self.assertContains(response, "calendar-event complete assignment")
        self.assertContains(response, "2/2 done")

    def test_started_incomplete_lecture_is_red_on_calendar(self):
        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today, time(0, 1)))
        end = timezone.make_aware(datetime.combine(today, time(23, 59)))
        lecture = Lecture.objects.create(
            section=self.section,
            title="Morning lecture",
            scheduled_start=start,
            scheduled_end=end,
            weekday=today.weekday(),
            slot=Lecture.Slot.AFTERNOON,
        )

        response = self.client.get(reverse("section_calendar"), {
            "month": today.strftime("%Y-%m"),
            "section": self.section.pk,
        })

        self.assertContains(response, "calendar-event incomplete lecture")
        self.assertContains(response, lecture.title)


class LectureScheduleTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="lecture-manager",
            password="test-password",
        )
        self.client.force_login(user)
        self.section = Section.objects.create(name="Lecture test section")

    def test_created_lecture_appears_in_list_and_detail_page(self):
        weekday = timezone.localdate().weekday()
        response = self.client.post(reverse("lecture_create"), {
            "section": self.section.pk,
            "weekday": weekday,
            "first_subject": "Newly scheduled lecture",
            "second_subject": "",
        })

        self.assertRedirects(response, reverse("lectures"))
        lecture = Lecture.objects.get(section=self.section, title="Newly scheduled lecture")
        self.assertContains(self.client.get(reverse("lectures")), lecture.title)
        self.assertContains(
            self.client.get(reverse("lecture_detail", args=[lecture.pk])),
            lecture.title,
        )

    def test_lecture_list_filters_by_section_and_weekday(self):
        matching_day = timezone.localdate().weekday()
        other_day = (matching_day + 1) % 7
        matching_lecture = Lecture.objects.create(
            section=self.section,
            title="Matching lecture",
            scheduled_start=timezone.make_aware(datetime.combine(timezone.localdate(), time(16))),
            scheduled_end=timezone.make_aware(datetime.combine(timezone.localdate(), time(19))),
            weekday=matching_day,
            slot=Lecture.Slot.AFTERNOON,
        )
        Lecture.objects.create(
            section=self.section,
            title="Other day lecture",
            scheduled_start=timezone.make_aware(datetime.combine(
                timezone.localdate() + timedelta(days=(other_day - matching_day) % 7),
                time(16),
            )),
            scheduled_end=timezone.make_aware(datetime.combine(
                timezone.localdate() + timedelta(days=(other_day - matching_day) % 7),
                time(19),
            )),
            weekday=other_day,
            slot=Lecture.Slot.AFTERNOON,
        )
        other_section = Section.objects.create(name="Another lecture section")
        Lecture.objects.create(
            section=other_section,
            title="Other section lecture",
            scheduled_start=timezone.make_aware(datetime.combine(timezone.localdate(), time(16))),
            scheduled_end=timezone.make_aware(datetime.combine(timezone.localdate(), time(19))),
            weekday=matching_day,
            slot=Lecture.Slot.AFTERNOON,
        )

        response = self.client.get(reverse("lectures"), {
            "section": self.section.pk,
            "weekday": matching_day,
        })

        self.assertEqual(list(response.context["lectures"]), [matching_lecture])
        self.assertContains(response, "lecture-cards")
        self.assertContains(response, matching_lecture.location or "Not specified")
        self.assertNotContains(response, "Other day lecture")
        self.assertNotContains(response, "Other section lecture")

    def test_lecture_list_day_filter_includes_one_off_lectures(self):
        lecture_date = timezone.localdate()
        lecture = Lecture.objects.create(
            section=self.section,
            title="One-off lecture",
            scheduled_start=timezone.make_aware(datetime.combine(lecture_date, time(16))),
            scheduled_end=timezone.make_aware(datetime.combine(lecture_date, time(17))),
        )

        response = self.client.get(reverse("lectures"), {"weekday": lecture_date.weekday()})

        self.assertContains(response, lecture.title)
