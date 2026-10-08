"""
The worker side: record each task as it starts, refresh it while it runs, delete it when
django-q saves the result.

A worker that dies or is killed for a timeout writes nothing, and django-q only logs
"reincarnated worker". The record it leaves behind is what lets the checker name the task.
"""

import logging
import os
import resource
import socket
import threading
import time
from multiprocessing import current_process

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django_q.conf import Conf
from django_q.models import Failure, Success, Task
from django_q.signals import pre_execute

from . import conf, store

logger = logging.getLogger("django_q_watchdog")

_lock = threading.Lock()
_wake = threading.Event()
_state = {"current": None, "thread": None}


def rss_mb():
    """Resident memory of this process, from /proc on Linux; None elsewhere."""
    try:
        with open("/proc/self/statm") as statm:
            pages = int(statm.read().split()[1])
        return round(pages * os.sysconf("SC_PAGE_SIZE") / 1024 / 1024, 1)
    except (OSError, ValueError, IndexError):
        return None


def cpu_seconds():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def build_record(task):
    kwargs = task.get("kwargs") or {}
    now = timezone.now().isoformat()
    memory = rss_mb()
    return {
        "task_id": str(task.get("id") or ""),
        "name": task.get("name"),
        "func": str(task.get("func") or ""),
        "group": task.get("group"),
        "tenant": kwargs.get(conf.get("TENANT_KWARG")) if isinstance(kwargs, dict) else None,
        "host": socket.gethostname(),
        "process": current_process().name,
        "pid": os.getpid(),
        # django-q has already removed a per-task timeout from the dict by now
        "timeout": task.get("timeout") or Conf.TIMEOUT,
        "started": now,
        "last_seen": now,
        "rss_mb": memory,
        "rss_start_mb": memory,
        "cpu_seconds": 0.0,
        "cpu_percent": 0,
    }


def start(task):
    record = build_record(task)
    store.save(record)
    with _lock:
        _state["current"] = {
            "record": record,
            "cpu_start": cpu_seconds(),
            "clock_start": time.monotonic(),
        }
    _ensure_thread()


def refresh():
    with _lock:
        current = _state["current"]
    if current is None:
        return
    record = current["record"]
    if store.get(record["task_id"]) is None:
        # django-q saved the task and our receiver deleted its record: nothing to track
        with _lock:
            if _state["current"] is current:
                _state["current"] = None
        return
    used = max(cpu_seconds() - current["cpu_start"], 0.0)
    elapsed = time.monotonic() - current["clock_start"]
    record.update(
        last_seen=timezone.now().isoformat(),
        rss_mb=rss_mb(),
        cpu_seconds=round(used, 1),
        cpu_percent=round(used / elapsed * 100) if elapsed > 0 else 0,
    )
    store.save(record, only_if_present=True)


def _loop():
    while True:
        _wake.wait(conf.get("HEARTBEAT_SECONDS"))
        try:
            refresh()
        except Exception:
            logger.exception("django-q-watchdog: heartbeat refresh failed")


def _ensure_thread():
    # One thread per worker process, started by the worker's first task. Threads don't
    # survive fork, so a fresh worker never inherits one.
    with _lock:
        thread = _state["thread"]
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(target=_loop, name="q-watchdog-heartbeat", daemon=True)
        _state["thread"] = thread
        thread.start()


@receiver(pre_execute)
def _on_pre_execute(sender, func=None, task=None, **kwargs):
    try:
        if isinstance(task, dict):
            start(task)
    except Exception:
        logger.exception("django-q-watchdog: could not record task start")


@receiver(post_save, sender=Task)
@receiver(post_save, sender=Success)
@receiver(post_save, sender=Failure)
def _on_task_saved(sender, instance=None, **kwargs):
    # Task rows are written by django-q's monitor when a task finishes, failed or not.
    try:
        if instance is not None:
            store.delete(instance.id)
    except Exception:
        logger.exception("django-q-watchdog: could not clear task record")
