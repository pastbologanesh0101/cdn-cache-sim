"""``cdnsim`` command line.

    cdnsim run     --requests 100000 --policy lru --edge-mb 64
    cdnsim compare --requests 100000
    cdnsim sweep   --policy lru        # hit ratio vs edge cache size
"""

from __future__ import annotations

import argparse
import json

from .simulator import Simulator, compare_policies
from .topology import Topology
from .workload import Catalog

REGIONS = ["us-east", "us-west", "eu", "apac"]


def _catalog_kwargs(ns):
    return dict(n_objects=ns.objects, zipf_s=ns.zipf, seed=ns.seed)


def _run_kwargs(ns):
    return dict(n_requests=ns.requests, arrival_rate=ns.rate,
                region_skew=ns.region_skew, seed=ns.seed + 1)


def cmd_run(ns) -> int:
    cat = Catalog(**_catalog_kwargs(ns))
    topo = Topology(REGIONS, policy=ns.policy,
                    edges_per_pop=ns.edges,
                    edge_capacity=ns.edge_mb * 1024 * 1024,
                    regional_capacity=ns.regional_mb * 1024 * 1024)
    sim = Simulator(topo, cat)
    sim.run(**_run_kwargs(ns))
    out = sim.metrics.summary()
    out["config"] = {"policy": ns.policy, "objects": ns.objects, "zipf_s": ns.zipf,
                     "edge_mb": ns.edge_mb, "edges_per_pop": ns.edges,
                     "working_set_top10pct_mb": round(cat.working_set_bytes() / 1e6, 1)}
    print(json.dumps(out, indent=2))
    return 0


def cmd_compare(ns) -> int:
    table = compare_policies(
        REGIONS, _catalog_kwargs(ns), _run_kwargs(ns),
        topo_kwargs=dict(edges_per_pop=ns.edges,
                         edge_capacity=ns.edge_mb * 1024 * 1024,
                         regional_capacity=ns.regional_mb * 1024 * 1024))
    cols = ["overall_hit_ratio", "edge_hit_ratio", "origin_offload", "bandwidth_saved"]
    print(f"{'policy':<8}" + "".join(f"{c:>20}" for c in cols) + f"{'p99_ms':>10}")
    for p, m in table.items():
        print(f"{p:<8}" + "".join(f"{m[c]:>20}" for c in cols)
              + f"{m['latency_ms']['p99']:>10}")
    best = max(table, key=lambda p: table[p]["overall_hit_ratio"])
    print(f"\nbest hit ratio: {best} ({table[best]['overall_hit_ratio']})")
    return 0


def cmd_sweep(ns) -> int:
    print(f"{'edge_MB':>8}{'overall_hit':>14}{'edge_hit':>12}{'offload':>10}{'p99_ms':>10}")
    for mb in (8, 16, 32, 64, 128, 256, 512):
        cat = Catalog(**_catalog_kwargs(ns))
        topo = Topology(REGIONS, policy=ns.policy, edges_per_pop=ns.edges,
                        edge_capacity=mb * 1024 * 1024)
        sim = Simulator(topo, cat)
        sim.run(**_run_kwargs(ns))
        m = sim.metrics.summary()
        print(f"{mb:>8}{m['overall_hit_ratio']:>14}{m['edge_hit_ratio']:>12}"
              f"{m['origin_offload']:>10}{m['latency_ms']['p99']:>10}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cdnsim")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(s):
        s.add_argument("--requests", type=int, default=100_000)
        s.add_argument("--objects", type=int, default=20_000)
        s.add_argument("--zipf", type=float, default=0.9)
        s.add_argument("--rate", type=float, default=200.0)
        s.add_argument("--region-skew", type=float, default=1.0)
        s.add_argument("--edges", type=int, default=2)
        s.add_argument("--edge-mb", type=int, default=64)
        s.add_argument("--regional-mb", type=int, default=512)
        s.add_argument("--seed", type=int, default=0)

    s = sub.add_parser("run"); common(s)
    s.add_argument("--policy", default="lru"); s.set_defaults(func=cmd_run)

    s = sub.add_parser("compare"); common(s); s.set_defaults(func=cmd_compare)

    s = sub.add_parser("sweep"); common(s)
    s.add_argument("--policy", default="lru"); s.set_defaults(func=cmd_sweep)
    return p


def main(argv=None) -> int:
    ns = build_parser().parse_args(argv)
    return ns.func(ns)


if __name__ == "__main__":
    raise SystemExit(main())
