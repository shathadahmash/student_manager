from django.contrib import admin
from .models import Enrollment, Lecture, Section, WorkItem

admin.site.register(Section)
admin.site.register(Lecture)
admin.site.register(Enrollment)
admin.site.register(WorkItem)
