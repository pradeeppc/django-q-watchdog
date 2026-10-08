"""Check django-q's running tasks, report lost and frozen ones, optionally fail for monitoring."""

import json

from django.core.management.base import BaseCommand, CommandError

from django_q_watchdog import checker

PROBLEMS = (checker.FROZEN, checker.TIMED_OUT, checker.LOST)


class Command(BaseCommand):
    help = "Report django-q tasks that are running, frozen, timed out, or lost with their worker"

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Print the reports as JSON")
        parser.add_argument(
            "--fail-on-problems",
            action="store_true",
            help="Exit with an error if any task is frozen, timed out, or lost (for monitoring)",
        )

    def handle(self, *args, **options):
        reports = [r for r in checker.check() if r["status"] != checker.FINISHED]
        summary = checker.summary(reports)

        if options["json"]:
            self.stdout.write(
                json.dumps({"summary": summary, "tasks": reports}, indent=2, default=str)
            )
        else:
            self.stdout.write(self._table(reports, summary))

        problems = [r for r in reports if r["status"] in PROBLEMS]
        if options["fail_on_problems"] and problems:
            raise CommandError(f"{len(problems)} django-q task(s) need attention")

    def _table(self, reports, summary):
        lines = [
            "  ".join(f"{k}: {v if v is not None else '?'}" for k, v in summary.items()),
            "",
        ]
        if not reports:
            lines.append("No tasks in flight.")
        for r in reports:
            lines.append(
                f"{r['status']:<10} {r.get('name') or r['task_id']:<40} "
                f"{r.get('tenant') or '-':<14} {r['running_for_seconds']:>7}s  "
                f"{r.get('host')}/{r.get('process')} pid {r.get('pid')}"
            )
            if r.get("reason"):
                lines.append(f"{'':<11}{r['reason']}")
        return "\n".join(lines) + "\n"
