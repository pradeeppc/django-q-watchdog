# django-q-watchdog

**Find the django-q tasks that crashed, timed out or froze, and say which ones.**

When a django-q worker process dies (out-of-memory kill, segfault, container restart), the
task it was running disappears: no row in Failed tasks, no error, no traceback. django-q only
logs `reincarnated worker Process-1:3 after death`. On the original django-q (1.3.x), a task
killed by the timeout disappears the same way. And a task that hangs looks exactly like one
that is working until the timeout finally kills it.

django-q-watchdog records every task as it starts, keeps a heartbeat while it runs, and tells
you what happened to the ones that never finished:

| Status | Meaning |
|---|---|
| `running` | Heartbeat is fresh. |
| `frozen` | Running for a long time with no memory change. Reported as **waiting** (almost no CPU: usually a network call or lock with no timeout) or **busy** (high CPU: possibly a loop). |
| `timed_out` | The worker was killed by django-q's timeout. |
| `lost` | The worker process died while running the task. |

Lost and timed-out tasks are saved into django-q's own **Failed tasks** (admin and
`Failure` model), with the worker, host and reason, so they show up where you already look.

## What django-q itself records

| Situation | django-q 1.3.x | django-q2 | with django-q-watchdog |
|---|---|---|---|
| Task raises an exception | Failed task | Failed task | unchanged |
| Task exceeds the timeout | **lost** | Failed task (raised inside the task) | timed out, saved as failed (1.3.x) |
| Worker process dies mid-task | **lost** | **lost** | lost, named, saved as failed |
| Task hangs | silent until the timeout | silent until the timeout | frozen: waiting or busy |

## Install

```bash
pip install django-q-watchdog
```

```python
INSTALLED_APPS = [
    # ...
    "django_q",
    "django_q_watchdog",
]
```

That's all the workers need: the heartbeat starts with each task. Then make sure problems get
reported without anyone looking. Run the check every few minutes from cron or your
scheduler:

```bash
python manage.py qwatchdog --fail-on-problems
```

It prints a table, logs one error per lost or frozen task to the `django_q_watchdog` logger,
and exits non-zero when something needs attention. Use `--json` for machine-readable output.

> Run it from cron or your platform's scheduler rather than as a django-q schedule: if the
> cluster itself is stuck, a django-q schedule won't run either.

## Alerts

Every problem is reported once, through the logger and a Django signal you can connect to
Slack, Sentry, PagerDuty and so on:

```python
from django.dispatch import receiver
from django_q_watchdog.signals import task_frozen, task_lost


@receiver(task_lost)
def notify_lost(sender, report, **kwargs):
    slack.post(f"Task {report['name']} ({report['func']}) {report['status']}: {report['reason']}")
```

`report` contains the task ID, name, function, group, tenant, host, process, PID, start time,
running time, memory and CPU.

## Status endpoint (optional)

```python
urlpatterns = [
    path("ops/q-watchdog/", include("django_q_watchdog.urls")),
]
```

Returns the in-flight tasks and a summary (running, frozen, timed out, lost, queued) as JSON.
It's **staff-only** by default because it names tasks, hosts and tenants. Change who can see it
with `ACCESS_CHECK`.

Example response, `GET /ops/q-watchdog/`:

```json
{
  "summary": {
    "running": 1,
    "frozen": 1,
    "timed_out": 0,
    "lost": 1,
    "queued": 0
  },
  "tasks": [
    {
      "task_id": "1a2b3c4d5e6f47a8b9c0d1e2f3a4b5c6",
      "name": "kilo-tango-river-seven",
      "func": "integrations.tasks.sync_employees",
      "group": null,
      "tenant": "globex",
      "host": "worker-1",
      "process": "Process-1:4",
      "pid": 4187,
      "timeout": 600,
      "started": "2026-10-08T17:55:13.260244+00:00",
      "last_seen": "2026-10-08T19:24:43.260244+00:00",
      "rss_mb": 150.2,
      "rss_start_mb": 150.0,
      "cpu_seconds": 1.2,
      "cpu_percent": 0,
      "status": "frozen",
      "reason": "waiting: almost no CPU, likely blocked on I/O or a lock",
      "running_for_seconds": 5400
    },
    {
      "task_id": "7c6b5a4f3e2d41c0b9a8f7e6d5c4b3a2",
      "name": "ruby-hotel-falcon-two",
      "func": "documents.tasks.generate_pdf",
      "group": null,
      "tenant": "acme",
      "host": "worker-1",
      "process": "Process-1:2",
      "pid": 4179,
      "timeout": 600,
      "started": "2026-10-08T19:14:33.260244+00:00",
      "last_seen": "2026-10-08T19:18:23.260244+00:00",
      "rss_mb": 1985.7,
      "rss_start_mb": 190.3,
      "cpu_seconds": 120.5,
      "cpu_percent": 98,
      "status": "lost",
      "reason": "the worker process died while running it",
      "running_for_seconds": 640
    },
    {
      "task_id": "9f8b2c1e4d7a4b6c8e0f1a2b3c4d5e6f",
      "name": "oscar-delta-nine-lemon",
      "func": "reports.tasks.export_payroll",
      "group": null,
      "tenant": "acme",
      "host": "worker-1",
      "process": "Process-1:3",
      "pid": 4182,
      "timeout": 600,
      "started": "2026-10-08T19:23:38.260244+00:00",
      "last_seen": "2026-10-08T19:25:01.260244+00:00",
      "rss_mb": 212.4,
      "rss_start_mb": 180.1,
      "cpu_seconds": 41.0,
      "cpu_percent": 43,
      "status": "running",
      "reason": null,
      "running_for_seconds": 95
    }
  ]
}
```

Reading it:

- **`sync_employees` is frozen and waiting.** It has run for 90 minutes on almost no CPU,
  and its memory hasn't moved. That usually means a call to another system with no timeout.
- **`generate_pdf` was lost.** Its memory grew from 190 MB to almost 2 GB before the worker
  died, which points to an out-of-memory kill. It is now also in django-q's Failed tasks.
- **`export_payroll` is running normally.**
- `last_seen` is the last heartbeat. `rss_start_mb` and `rss_mb` are the worker's memory when
  the task started and at the last heartbeat. `cpu_percent` is the task's average CPU use.
- `tenant` is `null` in projects without django-tenants.

The same data is available from `python manage.py qwatchdog --json`.

## Multi-tenant projects

With [django-tenants](https://github.com/django-tenants/django-tenants) and
django-tenants-q, each record carries the task's `schema_name`, and lost tasks are saved as
failures in that tenant's schema. Without django-tenants, nothing changes.

## Configuration

All optional:

```python
Q_WATCHDOG = {
    "CACHE": "default",  # must be django-redis, Django's RedisCache, or LocMemCache
    "HEARTBEAT_SECONDS": 60,
    "STALE_AFTER_SECONDS": 180,  # no heartbeat for this long: the worker is gone
    "FROZEN_AFTER_SECONDS": 3600,  # None turns frozen detection off
    "RECORD_TTL_SECONDS": 604800,
    "SAVE_LOST_AS_FAILED": True,  # put lost and timed-out tasks into django-q's Failed tasks
    "TENANT_KWARG": "schema_name",
    "ACCESS_CHECK": "django_q_watchdog.conf.staff_only",
}
```

The cache must be shared by your web processes and your cluster, which is why a Redis cache is
expected in production. Memory figures come from `/proc` and are Linux-only; everything else
works on any platform.

## How it works

- **In each worker:** django-q's `pre_execute` signal writes a record for the task, and a
  small thread refreshes it every `HEARTBEAT_SECONDS` with memory and CPU usage. A refresh only
  updates a record that still exists, so a finished task is never brought back.
- **When django-q saves the task** (success or failure), the record is deleted.
- **The check** looks at what's left: a record whose heartbeat stopped belongs to a worker that
  died or was killed; a record still refreshing but unchanged for an hour belongs to a frozen
  task.

Tested end to end against a real cluster, by killing worker processes and letting tasks hang
past the timeout, on django-q 1.3.9 with Django 4.2 and on django-q2 with Django 5.2.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
