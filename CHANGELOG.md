# Changelog

## [0.1.0] - Unreleased

First release.

- Heartbeat for every django-q task: name, function, tenant, host, PID, memory and CPU.
- `qwatchdog` command: reports running, frozen, timed-out and lost tasks; `--json` and
  `--fail-on-problems` for monitoring.
- Lost and timed-out tasks saved to django-q's Failed tasks.
- `task_lost` and `task_frozen` signals, sent once per problem.
- Staff-only JSON status endpoint.
- Works with django-q 1.3.9 and django-q2, with or without django-tenants.
