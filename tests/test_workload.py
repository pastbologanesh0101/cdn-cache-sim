from collections import Counter

from cdnsim.workload import Catalog, request_stream


def test_zipf_popularity_is_heavy_tailed():
    cat = Catalog(n_objects=1000, zipf_s=1.0, seed=0)
    draws = Counter(cat.sample().oid for _ in range(50_000))
    # obj0 is the most popular; it should dominate
    assert draws["obj0"] == max(draws.values())
    top10 = sum(c for _, c in draws.most_common(10))
    assert top10 / 50_000 > 0.20                      # top 10 of 1000 > 20% of hits


def test_zipf_s_controls_skew():
    flat = Catalog(n_objects=500, zipf_s=0.3, seed=1)
    steep = Catalog(n_objects=500, zipf_s=1.3, seed=1)
    f = Counter(flat.sample().oid for _ in range(30_000))
    s = Counter(steep.sample().oid for _ in range(30_000))
    assert s.most_common(1)[0][1] > f.most_common(1)[0][1] * 3


def test_object_sizes_and_ttls_assigned():
    cat = Catalog(n_objects=200, mean_ttl=100.0, uncacheable_frac=0.1, seed=2)
    assert all(o.size > 0 for o in cat.objects)
    assert any(o.cacheable is False for o in cat.objects)
    ttls = [o.ttl for o in cat.objects if o.cacheable]
    assert min(ttls) >= 0 and 20 < sum(ttls) / len(ttls) < 400


def test_request_stream_is_ordered_in_time_and_covers_regions():
    cat = Catalog(n_objects=100, seed=3)
    regions = ["a", "b", "c"]
    events = list(request_stream(cat, 5000, regions, arrival_rate=50, seed=4))
    times = [t for t, _, _ in events]
    assert times == sorted(times)
    assert set(r for _, r, _ in events) == {"a", "b", "c"}


def test_region_skew_biases_first_region():
    cat = Catalog(n_objects=50, seed=0)
    regions = ["r0", "r1", "r2", "r3"]
    skewed = Counter(r for _, r, _ in
                     request_stream(cat, 8000, regions, region_skew=1.5, seed=1))
    assert skewed["r0"] > skewed["r3"] * 2
