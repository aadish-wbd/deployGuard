from app.core.cache import TTLCache


def test_cache_hit_within_ttl():
    cache = TTLCache(ttl_seconds=300)
    key = TTLCache.make_key("boom", "payment-api", "production")
    cache.set(key, {"result": "ok"})
    assert cache.get(key) == {"result": "ok"}


def test_cache_miss_after_ttl_expires():
    cache = TTLCache(ttl_seconds=-1)
    key = TTLCache.make_key("boom", "payment-api", "production")
    cache.set(key, {"result": "ok"})
    assert cache.get(key) is None


def test_cache_key_stable_for_same_inputs():
    key1 = TTLCache.make_key("boom", "payment-api", "production")
    key2 = TTLCache.make_key("boom", "payment-api", "production")
    key3 = TTLCache.make_key("boom", "auth-api", "production")
    assert key1 == key2
    assert key1 != key3


def test_cache_key_differs_by_environment():
    prod = TTLCache.make_key("boom", "payment-api", "production")
    staging = TTLCache.make_key("boom", "payment-api", "staging")
    assert prod != staging
