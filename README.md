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
