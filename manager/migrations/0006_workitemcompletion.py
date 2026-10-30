import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("manager", "0005_examattendance"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkItemCompletion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("completed", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="work_completions", to="manager.student")),
                ("work_item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="completion_records", to="manager.workitem")),
            ],
            options={
                "ordering": ["student__academic_number"],
                "constraints": [
                    models.UniqueConstraint(fields=("student", "work_item"), name="unique_student_work_item_completion"),
                ],
            },
        ),
    ]
