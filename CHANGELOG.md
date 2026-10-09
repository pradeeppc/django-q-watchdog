# Changelog

## [0.1.1] - 2026-10-09

### Fixed

- A task whose memory grew early and then stopped moving was never reported as frozen, because
  frozen meant "same memory as at the start". It now means no memory change for
  `FROZEN_AFTER_SECONDS`, tracked as `memory_changed_at`.
- Waiting vs busy used the average CPU since the task started, so a task that worked hard and
  then got stuck was called "busy". It now uses `cpu_recent_percent`, the CPU since the
  previous heartbeat.
- Frozen detection is off when memory can't be measured (non-Linux), instead of flagging
  every long task.

## [0.1.0] - 2026-10-09

First release.

- Heartbeat for every django-q task: name, function, tenant, host, PID, memory and CPU.
- `qwatchdog` command: reports running, frozen, timed-out and lost tasks; `--json` and
  `--fail-on-problems` for monitoring.
- Lost and timed-out tasks saved to django-q's Failed tasks.
- `task_lost` and `task_frozen` signals, sent once per problem.
- Staff-only JSON status endpoint.
- Works with django-q 1.3.9 and django-q2, with or without django-tenants.
