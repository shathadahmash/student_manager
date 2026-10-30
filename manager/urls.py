from django.contrib.auth.views import LogoutView
from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.ManagerLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("attendance-report/", views.attendance_report, name="attendance_report"),
    path("calendar/", views.section_calendar, name="section_calendar"),
    path("calendar/<str:event_type>/<int:event_id>/<str:event_date>/", views.calendar_event, name="calendar_event"),
    path("sections/", views.section_list, name="sections"),
    path("students/", views.student_list, name="students"),
    path("students/add/", views.student_create, name="student_create"),
    path("students/import/", views.student_import, name="student_import"),
    path("students/<int:pk>/edit/", views.student_edit, name="student_edit"),
    path("students/<int:pk>/delete/", views.student_delete, name="student_delete"),
    path("lectures/", views.lecture_list, name="lectures"),
    path("lectures/add/", views.lecture_create, name="lecture_create"),
    path("lectures/<int:pk>/", views.lecture_detail, name="lecture_detail"),
    path("lectures/<int:pk>/edit/", views.lecture_edit, name="lecture_edit"),
    path("lectures/<int:pk>/delete/", views.lecture_delete, name="lecture_delete"),
    path("work/", views.work_list, name="work_items"),
    path("work/add/", views.work_create, name="work_create"),
    path("work/<int:pk>/edit/", views.work_edit, name="work_edit"),
    path("work/<int:pk>/delete/", views.work_delete, name="work_delete"),
]
