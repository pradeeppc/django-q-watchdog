import datetime

import pytest
from django.core.cache import cache
from django.utils import timezone

from django_q_watchdog import heartbeat, store


@pytest.fixture(autouse=True)
def clean_cache():
    cache.clear()
    heartbeat._state["current"] = None
    yield
    cache.clear()
    heartbeat._state["current"] = None


def django_q_task(task_id="a1b2c3", tenant="acme", name="echo-delta-four"):
    """The dict django-q passes to pre_execute."""
    return {
        "id": task_id,
        "name": name,
        "func": "reports.tasks.export_payroll",
        "args": (),
        "kwargs": {"schema_name": tenant} if tenant else {},
        "group": None,
    }


@pytest.fixture
def plant():
    """Store a heartbeat record that started and was last refreshed N seconds ago."""

    def _plant(started_ago, seen_ago, task_id="a1b2c3", **overrides):
        now = timezone.now()
        record = heartbeat.build_record(django_q_task(task_id))
        record.update(
            started=(now - datetime.timedelta(seconds=started_ago)).isoformat(),
            last_seen=(now - datetime.timedelta(seconds=seen_ago)).isoformat(),
            **overrides,
        )
        store.save(record)
        return record

    return _plant
