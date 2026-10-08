from django.apps import AppConfig


class QWatchdogConfig(AppConfig):
    name = "django_q_watchdog"
    verbose_name = "django-q watchdog"

    def ready(self):
        from . import heartbeat  # noqa: F401  connects the signal receivers
