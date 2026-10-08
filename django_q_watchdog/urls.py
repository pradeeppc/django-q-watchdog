from django.urls import path

from . import views

app_name = "django_q_watchdog"

urlpatterns = [
    path("", views.StatusView.as_view(), name="status"),
]
