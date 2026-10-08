from django.urls import include, path

urlpatterns = [path("q-watchdog/", include("django_q_watchdog.urls"))]
