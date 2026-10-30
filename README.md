# Campus Desk — local student and lecture manager

A locally run Django app for managing student records, sections, lecture assignments and completion, section-wide homework/assignments/exams, and due-date reminders. It is designed to connect to the MySQL/MariaDB service bundled with XAMPP.

## What it does

- Create and edit sections and student profiles (email, optional name, academic number, major and section). The Excel section number (`الشعبة`) is retained and displayed separately.
- Import students from an `.xlsx` workbook in the **Students** area. The importer reads the Arabic student name, email, password, specialization, group, period and university-number columns; groups become sections, duplicate records are skipped, and password values are saved only as Django one-way hashes.
- To sync a workbook with existing students, select **Update matching students** during import. It updates rows only when both email and university number match, replaces password hashes without displaying passwords, and preserves existing student records and their related data.
- Store entered student passwords as Django one-way hashes. Existing passwords cannot be viewed; edit a student and enter a new value to reset it.
- Set a weekly timetable for each section and weekday using two fixed local-time slots (4–7 PM and 7–10 PM). Enter a subject name only for slots that section has; all section students are included automatically.
- Create homework, assignments, exams or other work once for a section. The section association makes the item shared with all students in that section; optional lecture association narrows its academic context.
- Show today's one-time and recurring lectures and student email addresses on the dashboard, with a checkbox to record attendance per student, lecture, and date. Checked-in lecture students are hidden from today's roster; use **Show checked students** to review or undo attendance. They appear in the roster again on the next day. Today's exams also have per-student attendance checkboxes.
- Open **Attendance report** and choose a date to review lecture and exam rosters, including students checked in, students not checked in, and when attendance was last marked present.
- Open **Calendar** to filter a month by section and view lectures, homework, assignments and exams. Calendar items turn green when every student in that section is marked done; incomplete started/due items turn red. Open an event to update student statuses.
- Show overdue items and flag items due within 24 hours (for exams, due time is the exam end time).

## Requirements

- Python 3.10 or newer (tested with Python 3.12).
- XAMPP with MySQL/MariaDB running.
- Windows: use PowerShell in the extracted project folder. macOS/Linux can use the equivalent `python3`/`source` commands.

## Windows + XAMPP setup

1. Start **Apache** and **MySQL** from the XAMPP Control Panel (Apache is only needed for phpMyAdmin; Django uses its own development server).
2. Open `http://localhost/phpmyadmin`, create a database named `student_manager`, and select `utf8mb4_unicode_ci` as the collation.
3. Copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell). For a default XAMPP installation, the database values are typically `DB_USER=root`, `DB_PASSWORD=` (empty), `DB_HOST=127.0.0.1`, `DB_PORT=3306`. Change these if you set a MySQL password or a different port. Set `TIME_ZONE` to your local IANA timezone, such as `Europe/Istanbul`.
4. In PowerShell, from this project folder run:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   python manage.py check
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py runserver
   ```

5. Visit `http://127.0.0.1:8000/` and sign in using the staff username/password created in step 4.

If PowerShell prevents virtual-environment activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that PowerShell window, then activate again. Alternatively, use the venv Python directly: `.\.venv\Scripts\python.exe manage.py runserver`.

## Recommended first-use order

1. Add a section.
2. Add students to that section.
3. Use **Set section schedule** to select a section and weekday, then enter the subject name for either or both time slots. Leave a subject blank if that section has no lecture in that slot.
4. Add homework/exams by section. These appear in the common section list automatically.
5. Weekly schedules list all students in the section; attendance is not tracked separately for each weekly occurrence.

## Reminder and credential behavior

The dashboard displays work due in the next 24 hours and overdue items while the local app is running. It does **not** send email, SMS, operating-system notifications, or background alerts while the app is closed. Those can be added later if you want them and configure a mail or notification service.

Student password values are sensitive credentials. The Excel importer hashes password cells with Django's password hashing and does not save the uploaded workbook. The app cannot show the original password later. This is safer than storing or displaying a plaintext password, including on the dashboard. Use the edit-student form to set a new password when needed. Staff logins are separate Django accounts created with `createsuperuser`.

## Notes

- This is a local development app. Do not expose Django's `runserver` to the public internet. Before any public deployment, set a strong `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, a restricted `DJANGO_ALLOWED_HOSTS`, HTTPS, database backups and a proper production server.
- Work sharing is implemented by storing a single work item on a section, rather than cloning copies onto student rows.
- The default time zone in `.env.example` is `Europe/Istanbul`; update it to match your campus.
