import pytest
from django.utils import timezone
from django_q.models import Task
from django_q.signals import pre_execute

from django_q_watchdog import heartbeat, store
from tests.conftest import django_q_task


def test_task_start_is_recorded():
    pre_execute.send(sender="django_q", func=None, task=django_q_task())
    record = store.get("a1b2c3")
    assert record["name"] == "echo-delta-four"
    assert record["func"] == "reports.tasks.export_payroll"
    assert record["tenant"] == "acme"
    assert record["timeout"] == 600  # from Q_CLUSTER
    assert record["pid"] and record["host"]


def test_tenant_is_optional():
    pre_execute.send(sender="django_q", func=None, task=django_q_task(tenant=None))
    assert store.get("a1b2c3")["tenant"] is None


@pytest.mark.django_db
def test_saving_the_task_clears_its_record():
    pre_execute.send(sender="django_q", func=None, task=django_q_task())
    now = timezone.now()
    Task.objects.create(
        id="a1b2c3", name="echo-delta-four", func="x", started=now, stopped=now, success=True
    )
    assert store.get("a1b2c3") is None


def test_refresh_updates_a_running_task():
    heartbeat.start(django_q_task())
    first = store.get("a1b2c3")["last_seen"]
    heartbeat.refresh()
    record = store.get("a1b2c3")
    assert record["last_seen"] >= first
    assert record["cpu_seconds"] >= 0


def test_refresh_never_brings_back_a_finished_task():
    heartbeat.start(django_q_task())
    store.delete("a1b2c3")  # django-q saved it in the meantime
    heartbeat.refresh()
    assert store.get("a1b2c3") is None
    assert heartbeat._state["current"] is None


def test_a_broken_cache_never_breaks_the_task(monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(store, "save", broken)
    pre_execute.send(sender="django_q", func=None, task=django_q_task())  # must not raise
    assert "could not record task start" in caplog.text
