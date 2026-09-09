import pytest

from cdnsim.cache import (
    FIFOCache,
    LFUCache,
    LRUCache,
    S3FIFOCache,
    TTLCache,
    make_cache,
)


def fill(cache, *keys, size=10):
    for k in keys:
        cache.put(k, k, size)


def test_capacity_is_bytes_and_enforced():
    c = LRUCache(100)
    fill(c, *range(20), size=10)          # 20 * 10 = 200 -> only 10 fit
    assert c.used <= 100
    assert len(c) == 10


def test_object_larger_than_cache_is_never_stored():
    c = LRUCache(100)
    c.put("big", "big", 500)
    assert "big" not in c
    assert c.stats.admitted_bytes == 0


def test_fifo_evicts_oldest_regardless_of_use():
    c = FIFOCache(30)
    fill(c, "a", "b", "c", size=10)
    c.get("a")                            # use doesn't matter for FIFO
    c.put("d", "d", 10)                   # evicts "a"
    assert "a" not in c and {"b", "c", "d"} <= set(c._store)


def test_lru_evicts_least_recently_used():
    c = LRUCache(30)
    fill(c, "a", "b", "c", size=10)
    c.get("a")                            # "a" now MRU, "b" is LRU
    c.put("d", "d", 10)
    assert "b" not in c
    assert {"a", "c", "d"} == set(c._store)


def test_lfu_evicts_least_frequent():
    c = LFUCache(30)
    fill(c, "a", "b", "c", size=10)
    for _ in range(3):
        c.get("a")
    c.get("b")
    c.put("d", "d", 10)                   # "c" has freq 1 (lowest) -> evicted
    assert "c" not in c


def test_lfu_tiebreak_is_lru_among_equal_freq():
    c = LFUCache(30)
    fill(c, "a", "b", "c", size=10)       # all freq 1
    c.put("d", "d", 10)                   # evict the oldest freq-1 -> "a"
    assert "a" not in c


def test_s3fifo_is_scan_resistant():
    """A one-hit-wonder scan should not evict a hot object held in main."""
    c = S3FIFOCache(1000, small_ratio=0.1)
    # make "hot" genuinely hot
    c.put("hot", "hot", 100)
    for _ in range(5):
        c.get("hot")
    # now stream 50 unique cold objects (a scan)
    for i in range(50):
        c.put(f"cold{i}", "x", 100)
        c.get(f"cold{i}")
    assert "hot" in c                     # survived the scan


def test_hit_ratio_and_stats():
    c = LRUCache(100)
    c.put("a", "a", 10)
    assert c.get("a") == "a"
    assert c.get("missing") is None
    assert c.stats.hits == 1 and c.stats.misses == 1
    assert c.stats.hit_ratio == 0.5


def test_ttl_cache_expires_on_access_and_sweep():
    inner = LRUCache(1000)
    c = TTLCache(inner)
    c.put("x", "x", 10, now=0.0, ttl=100.0)
    assert c.get("x", now=50.0) == "x"
    assert c.get("x", now=150.0) is None   # expired on access
    assert "x" not in c

    c.put("y", "y", 10, now=0.0, ttl=10.0)
    c.put("z", "z", 10, now=0.0, ttl=None)
    assert c.sweep(now=20.0) == 1          # y swept, z kept
    assert "z" in c and "y" not in c


def test_registry():
    for name in ("fifo", "lru", "lfu", "s3fifo"):
        assert make_cache(name, 100).name == name
    with pytest.raises(ValueError):
        make_cache("arc", 100)
