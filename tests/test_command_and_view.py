import io
import json

import pytest
from django.core.management import CommandError, call_command

pytestmark = pytest.mark.django_db


def run(*args):
    out = io.StringIO()
    call_command("qwatchdog", *args, stdout=out)
    return out.getvalue()


def test_table_lists_problems(plant):
    plant(started_ago=400, seen_ago=300)
    out = run()
    assert "lost" in out and "echo-delta-four" in out and "acme" in out
    assert "worker process died" in out


def test_json_output(plant):
    plant(started_ago=30, seen_ago=10)
    data = json.loads(run("--json"))
    assert data["summary"]["running"] == 1
    assert data["tasks"][0]["name"] == "echo-delta-four"


def test_fail_on_problems(plant):
    plant(started_ago=400, seen_ago=300)
    with pytest.raises(CommandError, match="1 django-q task"):
        run("--fail-on-problems")


def test_no_problems_passes(plant):
    plant(started_ago=30, seen_ago=10)
    run("--fail-on-problems")


def test_status_view_is_staff_only(client, django_user_model):
    assert client.get("/q-watchdog/").status_code == 403
    client.force_login(django_user_model.objects.create_user("joe", password="pw"))
    assert client.get("/q-watchdog/").status_code == 403


def test_status_view_for_staff(client, django_user_model, plant):
    plant(started_ago=30, seen_ago=10)
    client.force_login(django_user_model.objects.create_user("ops", password="pw", is_staff=True))
    data = client.get("/q-watchdog/").json()
    assert data["summary"]["running"] == 1
