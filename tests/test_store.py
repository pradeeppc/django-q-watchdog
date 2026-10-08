import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured

from django_q_watchdog import store


def test_lists_only_watchdog_records():
    store.save({"task_id": "one"})
    store.save({"task_id": "two"})
    cache.set("unrelated", "value")
    assert sorted(r["task_id"] for r in store.records()) == ["one", "two"]


def test_only_if_present_does_not_create():
    store.save({"task_id": "gone"}, only_if_present=True)
    assert store.get("gone") is None


def test_unsupported_cache_is_explained(settings):
    settings.CACHES = {
        **settings.CACHES,
        "dummy": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
    }
    settings.Q_WATCHDOG = {"CACHE": "dummy"}
    with pytest.raises(ImproperlyConfigured, match="can list keys"):
        store.records()
