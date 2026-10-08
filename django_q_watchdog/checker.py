"""
Reads the heartbeat records and says what happened to each task that started and hasn't
been saved by django-q: still running, frozen, timed out, or lost with its worker.

Run it on a schedule (``manage.py qwatchdog``) so problems are reported even when nobody
is looking at the status page.
"""

import logging
from contextlib import nullcontext

from django.apps import apps
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_q.models import Task

from . import conf, signals, store

logger = logging.getLogger("django_q_watchdog")

RUNNING = "running"
FROZEN = "frozen"
TIMED_OUT = "timed_out"
LOST = "lost"
FINISHED = "finished"  # saved by django-q after all; the record is just cleaned up

FLAT_MEMORY_MB = 1.0
WAITING_CPU_PERCENT = 5


def tenant_context(tenant):
    """Task rows live in the tenant's schema under django-tenants; elsewhere there's one."""
    if tenant and apps.is_installed("django_tenants"):
        from django_tenants.utils import schema_context

        return schema_context(tenant)
    return nullcontext()


def task_saved(record):
    with tenant_context(record.get("tenant")):
        return Task.objects.filter(id=record["task_id"]).exists()


def age(value, now):
    moment = parse_datetime(value) if isinstance(value, str) else value
    return (now - moment).total_seconds() if moment else None


def classify(record, now):
    running_for = age(record.get("started"), now) or 0
    silent_for = age(record.get("last_seen"), now)

    if silent_for is None or silent_for > conf.get("STALE_AFTER_SECONDS"):
        if task_saved(record):
            return FINISHED, None
        active_for = running_for - (silent_for or 0)
        timeout = record.get("timeout")
        if timeout and active_for >= timeout - 2 * conf.get("HEARTBEAT_SECONDS"):
            return TIMED_OUT, f"killed by django-q's timeout of {timeout}s"
        return LOST, "the worker process died while running it"

    frozen_after = conf.get("FROZEN_AFTER_SECONDS")
    if frozen_after and running_for > frozen_after and _memory_flat(record):
        if (record.get("cpu_percent") or 0) < WAITING_CPU_PERCENT:
            return FROZEN, "waiting: almost no CPU, likely blocked on I/O or a lock"
        return FROZEN, "busy: high CPU with no memory change, possibly looping"

    return RUNNING, None


def _memory_flat(record):
    start, current = record.get("rss_start_mb"), record.get("rss_mb")
    if not isinstance(start, (int, float)) or not isinstance(current, (int, float)):
        return False
    return abs(current - start) < FLAT_MEMORY_MB


def check(now=None):
    """Classify every record, alert once per problem, and return the reports."""
    now = now or timezone.now()
    reports = []
    for record in store.records():
        try:
            status, reason = classify(record, now)
        except Exception:
            logger.exception("django-q-watchdog: could not classify task %s", record.get("task_id"))
            continue

        report = {
            **record,
            "status": status,
            "reason": reason,
            "running_for_seconds": round(age(record.get("started"), now) or 0),
        }
        reports.append(report)

        if status == FINISHED:
            store.delete(record["task_id"])
        elif status in (LOST, TIMED_OUT):
            _handle_lost(record, report, now)
        elif status == FROZEN:
            _alert_once(record, FROZEN, report, logging.WARNING, signals.task_frozen)

    return sorted(reports, key=lambda r: r.get("started") or "")


def _alert_once(record, kind, report, level, signal):
    if kind in store.alerts(record["task_id"]):
        return False
    logger.log(
        level,
        "django-q task %s: %s | task %s (%s) | tenant %s | worker %s/%s pid %s | "
        "ran %ss | rss %s MB | cpu %s%%",
        report["status"],
        report["reason"],
        report.get("name"),
        report.get("func"),
        report.get("tenant") or "-",
        report.get("host"),
        report.get("process"),
        report.get("pid"),
        report["running_for_seconds"],
        report.get("rss_mb"),
        report.get("cpu_percent"),
    )
    signal.send(sender=check, report=report)
    store.mark_alerted(record["task_id"], kind)
    return True


def _handle_lost(record, report, now):
    if not _alert_once(record, report["status"], report, logging.ERROR, signals.task_lost):
        return
    if conf.get("SAVE_LOST_AS_FAILED"):
        save_as_failure(record, report, now)


def save_as_failure(record, report, now):
    """
    Put the task in django-q's Failed tasks, where people already look. Saving the row
    also clears the record, through the same post_save hook as any finished task.
    """
    started = parse_datetime(record.get("started") or "") or now
    message = (
        f"django-q-watchdog: {report['status']} ({report['reason']}) on "
        f"{record.get('host')}/{record.get('process')} pid {record.get('pid')}"
    )
    with tenant_context(record.get("tenant")):
        if Task.objects.filter(id=record["task_id"]).exists():
            return
        Task.objects.create(
            id=record["task_id"],
            name=(record.get("name") or record["task_id"])[:100],
            func=(record.get("func") or "unknown")[:256],
            group=record.get("group"),
            started=started,
            stopped=now,
            result=message,
            success=False,
            attempt_count=1,
        )


def summary(reports):
    counts = dict.fromkeys((RUNNING, FROZEN, TIMED_OUT, LOST), 0)
    for report in reports:
        if report["status"] in counts:
            counts[report["status"]] += 1
    counts["queued"] = queue_size()
    return counts


def queue_size():
    try:
        from django_q.brokers import get_broker

        return get_broker().queue_size()
    except Exception:
        return None
