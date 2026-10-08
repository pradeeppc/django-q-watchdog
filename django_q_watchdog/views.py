from django.http import JsonResponse
from django.views import View

from . import checker, conf


class StatusView(View):
    """In-flight tasks as JSON. Staff-only by default: it names tasks, hosts and tenants."""

    def get(self, request):
        if not conf.has_access(request):
            return JsonResponse(
                {"detail": "Staff only. See Q_WATCHDOG['ACCESS_CHECK']."}, status=403
            )
        reports = [r for r in checker.check() if r["status"] != checker.FINISHED]
        return JsonResponse({"summary": checker.summary(reports), "tasks": reports})
