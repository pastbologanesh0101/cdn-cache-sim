"""Vercel serverless function: run the CDN cache-hierarchy simulation.

POST {
  "mode": "run" | "compare" | "sweep",
  "policy": "lru", "objects": 15000, "zipf": 0.9,
  "edge_mb": 64, "regional_mb": 512, "requests": 40000, "region_skew": 1.2
}
"""

from http.server import BaseHTTPRequestHandler
import json

from cdnsim.simulator import Simulator, compare_policies
from cdnsim.topology import Topology
from cdnsim.workload import Catalog

REGIONS = ["us-east", "us-west", "eu", "apac"]
POLICIES = ["fifo", "lru", "lfu", "s3fifo"]
MAX_REQ = 60_000
MAX_OBJ = 40_000


def _cat_kw(d):
    return dict(n_objects=max(500, min(int(d.get("objects", 15_000)), MAX_OBJ)),
                zipf_s=max(0.3, min(float(d.get("zipf", 0.9)), 1.6)),
                mean_ttl=None, seed=0)


def _run_kw(d):
    return dict(n_requests=max(2000, min(int(d.get("requests", 40_000)), MAX_REQ)),
                arrival_rate=300.0,
                region_skew=max(0.0, min(float(d.get("region_skew", 1.2)), 3.0)),
                seed=1)


def _topo_kw(d):
    return dict(edges_per_pop=2,
                edge_capacity=max(1, min(int(d.get("edge_mb", 64)), 4096)) * 1024 * 1024,
                regional_capacity=max(1, min(int(d.get("regional_mb", 512)), 8192)) * 1024 * 1024)


def handle(d: dict) -> dict:
    mode = d.get("mode", "run")
    cat_kw, run_kw, topo_kw = _cat_kw(d), _run_kw(d), _topo_kw(d)

    if mode == "compare":
        table = compare_policies(REGIONS, cat_kw, run_kw, policies=POLICIES,
                                 topo_kwargs=topo_kw)
        best = max(table, key=lambda p: table[p]["overall_hit_ratio"])
        return {"ok": True, "kind": "compare", "table": table, "best": best,
                "requests": run_kw["n_requests"], "edge_mb": d.get("edge_mb", 64)}

    if mode == "sweep":
        rows = []
        for mb in (8, 16, 32, 64, 128, 256, 512, 1024):
            cat = Catalog(**cat_kw)
            topo = Topology(REGIONS, policy=d.get("policy", "lru"),
                            edges_per_pop=2, edge_capacity=mb * 1024 * 1024)
            m = Simulator(topo, cat).run(**run_kw).summary()
            rows.append({"edge_mb": mb, "overall_hit_ratio": m["overall_hit_ratio"],
                         "edge_hit_ratio": m["edge_hit_ratio"],
                         "origin_offload": m["origin_offload"],
                         "p99_ms": m["latency_ms"]["p99"]})
        return {"ok": True, "kind": "sweep", "policy": d.get("policy", "lru"), "rows": rows}

    policy = d.get("policy", "lru")
    if policy not in POLICIES:
        return {"ok": False, "text": f"unknown policy {policy!r}"}
    cat = Catalog(**cat_kw)
    topo = Topology(REGIONS, policy=policy, **topo_kw)
    m = Simulator(topo, cat).run(**run_kw).summary()
    return {"ok": True, "kind": "run", "policy": policy,
            "requests": run_kw["n_requests"],
            "working_set_top10pct_mb": round(cat.working_set_bytes() / 1e6, 1),
            "summary": m}


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self._send(204, {})

    def do_POST(self):  # noqa: N802
        try:
            n = int(self.headers.get("Content-Length") or 0)
            self._send(200, handle(json.loads(self.rfile.read(n) or b"{}")))
        except Exception as e:  # noqa: BLE001
            self._send(200, {"ok": False, "text": f"{type(e).__name__}: {e}"})

    def do_GET(self):  # noqa: N802
        self._send(200, {"ok": True, "text": "POST simulation params here"})
