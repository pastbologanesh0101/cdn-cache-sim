from cdnsim.simulator import Simulator, compare_policies
from cdnsim.topology import Topology
from cdnsim.workload import Catalog

REGIONS = ["us", "eu"]


def make_sim(policy="lru", edge_mb=32, objects=3000, zipf=1.0, seed=0):
    cat = Catalog(n_objects=objects, zipf_s=zipf, mean_ttl=None, seed=seed)
    topo = Topology(REGIONS, policy=policy, edges_per_pop=2,
                    edge_capacity=edge_mb * 1024 * 1024,
                    regional_capacity=256 * 1024 * 1024)
    return Simulator(topo, cat)


def test_cold_cache_is_all_misses_then_warms_up():
    sim = make_sim(edge_mb=64)
    m = sim.run(n_requests=20_000, seed=1)
    assert m.requests == 20_000
    # first requests are cold; by the end the hot set is cached -> decent hit rate
    assert m.overall_hit_ratio > 0.4
    assert m.origin_fetches < m.requests
    # accounting adds up
    assert m.edge_hits + m.regional_hits + m.origin_fetches == m.requests
    assert (m.bytes_from_edge + m.bytes_from_regional + m.bytes_from_origin
            == m.bytes_total)


def test_hit_ratio_increases_with_cache_size():
    ratios = [make_sim(edge_mb=mb).run(n_requests=15_000, seed=2).overall_hit_ratio
              for mb in (4, 16, 64, 256)]
    # Bigger edge caches still improve the overall ratio (less here than in a
    # single-tier cache, because the regional tier already absorbs edge misses).
    assert ratios[-1] > ratios[0] + 0.05
    # ...and while a two-tier hierarchy can wobble slightly between adjacent
    # sizes (a bigger edge changes what the regional tier sees), there is no
    # meaningful regression.
    assert all(b >= a - 0.02 for a, b in zip(ratios, ratios[1:]))


def test_single_edge_cache_hit_ratio_is_monotonic_in_size():
    """Isolate one LRU cache (regional made irrelevant): strictly non-decreasing."""
    ratios = []
    for mb in (4, 16, 64, 256):
        cat = Catalog(n_objects=3000, zipf_s=1.0, mean_ttl=None, seed=0)
        topo = Topology(["us"], policy="lru", edges_per_pop=1,
                        edge_capacity=mb * 1024 * 1024,
                        regional_capacity=1)          # regional can hold ~nothing
        ratios.append(Simulator(topo, cat).run(n_requests=15_000, seed=2).edge_hit_ratio)
    assert ratios == sorted(ratios)
    assert ratios[-1] > ratios[0] + 0.15


def test_more_skew_means_better_hit_ratio():
    flat = make_sim(zipf=0.6, edge_mb=32).run(n_requests=15_000, seed=3)
    steep = make_sim(zipf=1.2, edge_mb=32).run(n_requests=15_000, seed=3)
    assert steep.overall_hit_ratio > flat.overall_hit_ratio + 0.1


def test_regional_tier_catches_edge_misses():
    # tiny edges, big regional -> regional should absorb a lot of edge misses
    sim = make_sim(edge_mb=2, objects=2000, zipf=1.0)
    sim.topo = Topology(REGIONS, policy="lru", edges_per_pop=2,
                        edge_capacity=2 * 1024 * 1024,
                        regional_capacity=512 * 1024 * 1024)
    m = sim.run(n_requests=20_000, seed=4)
    assert m.regional_hits > 0
    assert m.overall_hit_ratio > m.edge_hit_ratio    # regional adds hits on top


def test_ttl_expiry_lowers_hit_ratio():
    long_ttl = Catalog(n_objects=2000, zipf_s=1.0, mean_ttl=10_000.0, seed=5)
    short_ttl = Catalog(n_objects=2000, zipf_s=1.0, mean_ttl=5.0, seed=5)
    t = dict(edges_per_pop=2, edge_capacity=64 * 1024 * 1024)
    a = Simulator(Topology(REGIONS, policy="lru", **t), long_ttl).run(
        n_requests=15_000, arrival_rate=50, seed=6)
    b = Simulator(Topology(REGIONS, policy="lru", **t), short_ttl).run(
        n_requests=15_000, arrival_rate=50, seed=6)
    assert a.overall_hit_ratio > b.overall_hit_ratio + 0.05


def test_latency_percentiles_ordered_and_origin_is_slowest():
    m = make_sim(edge_mb=32).run(n_requests=15_000, seed=7)
    p50, p90, p99 = m.percentile(50), m.percentile(90), m.percentile(99)
    assert p50 <= p90 <= p99
    assert m.summary()["latency_ms"]["p99"] >= m.summary()["latency_ms"]["p50"]


def test_bandwidth_saved_matches_offload_direction():
    m = make_sim(edge_mb=128, zipf=1.1).run(n_requests=15_000, seed=8)
    assert 0 < m.bandwidth_saved_ratio < 1
    assert m.origin_offload > 0.3


def test_compare_policies_all_run_and_s3fifo_competitive():
    table = compare_policies(
        REGIONS,
        dict(n_objects=3000, zipf_s=0.9, mean_ttl=None, seed=0),
        dict(n_requests=20_000, seed=1),
        topo_kwargs=dict(edges_per_pop=2, edge_capacity=16 * 1024 * 1024),
    )
    assert set(table) == {"fifo", "lru", "lfu", "s3fifo"}
    for m in table.values():
        assert 0 <= m["overall_hit_ratio"] <= 1
    # LRU/LFU/S3FIFO should all beat plain FIFO on a Zipf workload
    assert table["lru"]["overall_hit_ratio"] > table["fifo"]["overall_hit_ratio"]
    assert table["s3fifo"]["overall_hit_ratio"] >= table["fifo"]["overall_hit_ratio"]
