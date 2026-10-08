"""Settings, read from ``settings.Q_WATCHDOG``. See the README for each option."""

from django.conf import settings
from django.utils.module_loading import import_string

DEFAULTS = {
    "CACHE": "default",
    "KEY_PREFIX": "q_watchdog",
    "HEARTBEAT_SECONDS": 60,
    "STALE_AFTER_SECONDS": 180,  # three missed heartbeats
    "FROZEN_AFTER_SECONDS": 3600,  # None turns frozen detection off
    "RECORD_TTL_SECONDS": 7 * 24 * 3600,
    "SAVE_LOST_AS_FAILED": True,
    "TENANT_KWARG": "schema_name",
    "ACCESS_CHECK": "django_q_watchdog.conf.staff_only",
}


def get(name):
    return getattr(settings, "Q_WATCHDOG", {}).get(name, DEFAULTS[name])


def staff_only(request):
    user = getattr(request, "user", None)
    return bool(user and user.is_active and user.is_staff)


def has_access(request):
    check = get("ACCESS_CHECK")
    if isinstance(check, str):
        check = import_string(check)
    return bool(check(request))
