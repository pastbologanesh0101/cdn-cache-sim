"""Three quick studies on the same Zipf workload:

1. eviction policy vs hit ratio
2. edge cache size vs origin offload (the CDN capacity-planning question)
3. traffic skew vs cacheability

    python examples/demo.py
"""

from cdnsim import Catalog, Simulator, Topology, compare_policies

REGIONS = ["us-east", "us-west", "eu", "apac"]
CAT_KW = dict(n_objects=15_000, zipf_s=0.9, mean_ttl=None, seed=0)
RUN_KW = dict(n_requests=80_000, arrival_rate=300.0, region_skew=1.2, seed=1)

print("== 1. eviction policy (edge = 32 MB) ==")
table = compare_policies(REGIONS, CAT_KW, RUN_KW,
                         topo_kwargs=dict(edge_capacity=32 * 1024 * 1024))
print(f"{'policy':<8}{'overall_hit':>13}{'edge_hit':>11}{'offload':>10}{'p99_ms':>9}")
for p, m in table.items():
    print(f"{p:<8}{m['overall_hit_ratio']:>13}{m['edge_hit_ratio']:>11}"
          f"{m['origin_offload']:>10}{m['latency_ms']['p99']:>9}")

print("\n== 2. edge cache size vs origin offload (LRU) ==")
print(f"{'edge_MB':>8}{'edge_hit':>10}{'offload':>10}{'GB_from_origin':>16}")
for mb in (8, 32, 128, 512, 2048):
    cat = Catalog(**CAT_KW)
    topo = Topology(REGIONS, policy="lru", edge_capacity=mb * 1024 * 1024)
    m = Simulator(topo, cat).run(**RUN_KW).summary()
    print(f"{mb:>8}{m['edge_hit_ratio']:>10}{m['origin_offload']:>10}"
          f"{m['gb_from_origin']:>16}")

print("\n== 3. popularity skew (Zipf s) vs hit ratio, edge = 64 MB, LRU ==")
print(f"{'zipf_s':>8}{'overall_hit':>13}{'bandwidth_saved':>17}")
for s in (0.6, 0.8, 1.0, 1.2, 1.4):
    cat = Catalog(n_objects=15_000, zipf_s=s, mean_ttl=None, seed=0)
    topo = Topology(REGIONS, policy="lru", edge_capacity=64 * 1024 * 1024)
    m = Simulator(topo, cat).run(**RUN_KW).summary()
    print(f"{s:>8}{m['overall_hit_ratio']:>13}{m['bandwidth_saved']:>17}")
