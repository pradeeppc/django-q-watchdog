"""
Heartbeat records in Django's cache: one key per running task.

Listing keys isn't part of Django's cache API, so it's done per backend: django-redis,
Django's built-in Redis cache, and the local-memory cache (for tests and development).
"""

from fnmatch import fnmatch

from django.core.cache import caches
from django.core.exceptions import ImproperlyConfigured

from . import conf


def cache():
    return caches[conf.get("CACHE")]


def key(task_id):
    return f"{conf.get('KEY_PREFIX')}:task:{task_id}"


def pattern():
    return f"{conf.get('KEY_PREFIX')}:task:*"


def _is_django_redis(backend):
    return type(backend).__module__.startswith("django_redis")


def save(record, only_if_present=False):
    """
    Write a record. ``only_if_present`` is for the heartbeat's refresh: the task may have
    finished and its record been deleted since the last refresh, and a refresh must not
    bring it back.
    """
    backend = cache()
    record_key = key(record["task_id"])
    ttl = conf.get("RECORD_TTL_SECONDS")
    if not only_if_present:
        backend.set(record_key, record, ttl)
    elif _is_django_redis(backend):
        backend.set(record_key, record, ttl, xx=True)
    elif backend.get(record_key) is not None:
        # Other backends can't set-if-exists atomically. If this loses a race with the
        # task finishing, the checker finds the saved task and clears the record.
        backend.set(record_key, record, ttl)


def delete(task_id):
    cache().delete_many([key(task_id), alerts_key(task_id)])


def alerts_key(task_id):
    # Kept apart from the record: the worker rewrites the record on every heartbeat, and
    # would otherwise erase the fact that an alert was already sent.
    return f"{conf.get('KEY_PREFIX')}:alerted:{task_id}"


def alerts(task_id):
    return set(cache().get(alerts_key(task_id)) or ())


def mark_alerted(task_id, kind):
    cache().set(
        alerts_key(task_id), sorted(alerts(task_id) | {kind}), conf.get("RECORD_TTL_SECONDS")
    )


def get(task_id):
    return cache().get(key(task_id))


def records():
    backend = cache()
    keys = list_keys(backend, pattern())
    found = backend.get_many(keys) if keys else {}
    return [record for record in found.values() if record]


def list_keys(backend, match):
    if hasattr(backend, "iter_keys"):  # django-redis
        return list(backend.iter_keys(match))

    module = type(backend).__module__
    prefix = backend.make_key("")

    if module == "django.core.cache.backends.redis":
        client = backend._cache.get_client(None, write=False)
        raw = client.scan_iter(match=backend.make_key(match))
        return [
            k.decode()[len(prefix) :] if isinstance(k, bytes) else k[len(prefix) :] for k in raw
        ]

    if module == "django.core.cache.backends.locmem":
        return [k[len(prefix) :] for k in list(backend._cache) if fnmatch(k[len(prefix) :], match)]

    raise ImproperlyConfigured(
        "django-q-watchdog needs a cache that can list keys: django-redis, Django's "
        "RedisCache, or LocMemCache. Point Q_WATCHDOG['CACHE'] at one of them."
    )
