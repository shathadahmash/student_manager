import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("manager", "0004_lectureattendance"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExamAttendance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("attendance_date", models.DateField()),
                ("present", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("exam", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attendance_records", to="manager.workitem")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="exam_attendance", to="manager.student")),
            ],
            options={
                "ordering": ["exam__starts_at", "student__academic_number"],
                "constraints": [
                    models.UniqueConstraint(fields=("student", "exam", "attendance_date"), name="unique_student_exam_attendance_day"),
                ],
            },
        ),
    ]
