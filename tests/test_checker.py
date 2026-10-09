import datetime
import logging

import pytest
from django.utils import timezone
from django_q.models import Failure, Task

from django_q_watchdog import checker, signals, store

pytestmark = pytest.mark.django_db


def statuses():
    return {r["task_id"]: r["status"] for r in checker.check()}


def test_a_fresh_task_is_running(plant):
    plant(started_ago=30, seen_ago=10)
    assert statuses() == {"a1b2c3": checker.RUNNING}


def test_a_task_whose_worker_died_is_lost_alerted_once_and_saved_as_failed(plant, caplog):
    plant(started_ago=400, seen_ago=300)  # silent for 5 minutes, well before the 600s timeout
    received = []
    signals.task_lost.connect(lambda sender, report, **kw: received.append(report), weak=False)

    with caplog.at_level(logging.ERROR, logger="django_q_watchdog"):
        reports = checker.check()

    assert reports[0]["status"] == checker.LOST
    assert reports[0]["reason"] == "the worker process died while running it"
    assert "echo-delta-four" in caplog.text and "tenant acme" in caplog.text
    assert [r["task_id"] for r in received] == ["a1b2c3"]

    failure = Failure.objects.get(id="a1b2c3")
    assert failure.success is False
    assert "worker process died" in failure.result
    assert store.get("a1b2c3") is None  # recorded now, so the record is cleared

    caplog.clear()
    assert checker.check() == []
    assert caplog.text == ""


def test_a_task_killed_by_the_timeout_is_reported_as_timed_out(plant):
    plant(started_ago=900, seen_ago=300)  # was alive for ~600s, the configured timeout
    report = checker.check()[0]
    assert report["status"] == checker.TIMED_OUT
    assert "timeout of 600s" in report["reason"]
    assert Failure.objects.filter(id="a1b2c3").exists()


def test_a_lost_task_that_was_saved_after_all_is_just_cleaned_up(plant, caplog):
    now = timezone.now()
    Task.objects.create(id="a1b2c3", name="n", func="f", started=now, stopped=now)
    # a record left behind after the task was saved, e.g. by a refresh racing the save
    plant(started_ago=400, seen_ago=300)
    with caplog.at_level(logging.ERROR, logger="django_q_watchdog"):
        reports = checker.check()
    assert reports[0]["status"] == checker.FINISHED
    assert caplog.text == ""
    assert store.get("a1b2c3") is None


def test_lost_tasks_are_kept_but_not_realerted_when_not_saving_failures(plant, settings, caplog):
    settings.Q_WATCHDOG = {"SAVE_LOST_AS_FAILED": False}
    plant(started_ago=400, seen_ago=300)
    with caplog.at_level(logging.ERROR, logger="django_q_watchdog"):
        checker.check()
        first = caplog.text
        caplog.clear()
        second = checker.check()
    assert "lost" in first
    assert caplog.text == ""
    assert second[0]["status"] == checker.LOST
    assert not Failure.objects.exists()


def ago(seconds):
    return (timezone.now() - datetime.timedelta(seconds=seconds)).isoformat()


def test_frozen_and_waiting(plant, caplog):
    plant(started_ago=7200, seen_ago=20, memory_changed_at=ago(7200), cpu_recent_percent=0)
    with caplog.at_level(logging.WARNING, logger="django_q_watchdog"):
        report = checker.check()[0]
    assert report["status"] == checker.FROZEN
    assert report["reason"].startswith("waiting")
    assert "frozen" in caplog.text


def test_frozen_and_busy(plant):
    plant(started_ago=7200, seen_ago=20, memory_changed_at=ago(7200), cpu_recent_percent=97)
    assert checker.check()[0]["reason"].startswith("busy")


def test_a_task_that_grew_then_hung_is_frozen(plant):
    # loaded 300 MB in its first minutes, then stuck for 90 minutes
    plant(
        started_ago=6000,
        seen_ago=20,
        rss_start_mb=120.0,
        rss_mb=420.0,
        memory_changed_at=ago(5400),
        cpu_recent_percent=0,
    )
    report = checker.check()[0]
    assert report["status"] == checker.FROZEN
    assert report["reason"].startswith("waiting")


def test_recent_cpu_decides_waiting_even_after_busy_work(plant):
    # averaged 80% CPU over its life, but has used none in the last interval
    plant(
        started_ago=7200,
        seen_ago=20,
        memory_changed_at=ago(4000),
        cpu_percent=80,
        cpu_recent_percent=0,
    )
    assert checker.check()[0]["reason"].startswith("waiting")


def test_a_long_task_whose_memory_still_moves_is_not_frozen(plant):
    plant(started_ago=7200, seen_ago=20, memory_changed_at=ago(30), cpu_recent_percent=60)
    assert statuses() == {"a1b2c3": checker.RUNNING}


def test_without_a_memory_reading_nothing_is_flagged_frozen(plant):
    plant(started_ago=7200, seen_ago=20, rss_mb=None, memory_changed_at=ago(7200))
    assert statuses() == {"a1b2c3": checker.RUNNING}


def test_frozen_detection_can_be_turned_off(plant, settings):
    settings.Q_WATCHDOG = {"FROZEN_AFTER_SECONDS": None}
    plant(started_ago=7200, seen_ago=20, memory_changed_at=ago(7200), cpu_recent_percent=0)
    assert statuses() == {"a1b2c3": checker.RUNNING}


def test_summary_counts(plant):
    plant(started_ago=30, seen_ago=10, task_id="t-running")
    plant(started_ago=400, seen_ago=300, task_id="t-lost")
    summary = checker.summary(checker.check())
    assert summary["running"] == 1
    assert summary["lost"] == 1
    assert summary["queued"] == 0


def test_a_heartbeat_rewriting_the_record_does_not_repeat_the_frozen_alert(plant, caplog):
    record = plant(started_ago=7200, seen_ago=20, memory_changed_at=ago(7200), cpu_recent_percent=0)
    with caplog.at_level(logging.WARNING, logger="django_q_watchdog"):
        checker.check()
        store.save(record)  # the worker's next heartbeat writes its own copy of the record
        caplog.clear()
        checker.check()
    assert caplog.text == ""
