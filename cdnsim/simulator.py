"""Trace-driven CDN simulation.

Requests arrive as a Poisson process (from :func:`workload.request_stream`).
Each is served by walking up the hierarchy from the sharded edge to the origin,
filling caches on the way back down, and the end-to-end latency is recorded.
Virtual time advances with the arrival stream; there is no per-node queueing
(see the README's limitations).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .topology import Node, Topology
from .workload import Catalog, Obj, request_stream


@dataclass
class Metrics:
    requests: int = 0
    edge_hits: int = 0
    regional_hits: int = 0
    origin_fetches: int = 0
    bytes_total: int = 0
    bytes_from_edge: int = 0
    bytes_from_regional: int = 0
    bytes_from_origin: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    uncacheable: int = 0

    def record(self, source: str, size: int, latency_s: float, cacheable: bool) -> None:
        self.requests += 1
        self.bytes_total += size
        self.latencies_ms.append(latency_s * 1000.0)
        if not cacheable:
            self.uncacheable += 1
        if source == "edge":
            self.edge_hits += 1
            self.bytes_from_edge += size
        elif source == "regional":
            self.regional_hits += 1
            self.bytes_from_regional += size
        else:
            self.origin_fetches += 1
            self.bytes_from_origin += size

    # -- derived ------------------------------------------
    @property
    def edge_hit_ratio(self) -> float:
        return self.edge_hits / self.requests if self.requests else 0.0

    @property
    def overall_hit_ratio(self) -> float:
        return (self.edge_hits + self.regional_hits) / self.requests if self.requests else 0.0

    @property
    def origin_offload(self) -> float:
        return 1 - self.origin_fetches / self.requests if self.requests else 0.0

    @property
    def bandwidth_saved_ratio(self) -> float:
        return 1 - self.bytes_from_origin / self.bytes_total if self.bytes_total else 0.0

    def percentile(self, p: float) -> float:
        if not self.latencies_ms:
            return 0.0
        s = sorted(self.latencies_ms)
        i = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
        return s[i]

    def summary(self) -> dict:
        return {
            "requests": self.requests,
            "edge_hit_ratio": round(self.edge_hit_ratio, 4),
            "overall_hit_ratio": round(self.overall_hit_ratio, 4),
            "origin_offload": round(self.origin_offload, 4),
            "bandwidth_saved": round(self.bandwidth_saved_ratio, 4),
            "latency_ms": {
                "p50": round(self.percentile(50), 2),
                "p90": round(self.percentile(90), 2),
                "p99": round(self.percentile(99), 2),
                "mean": round(sum(self.latencies_ms) / len(self.latencies_ms), 2)
                if self.latencies_ms else 0.0,
            },
            "gb_from_origin": round(self.bytes_from_origin / 1e9, 3),
            "gb_from_edge": round(self.bytes_from_edge / 1e9, 3),
        }


class Simulator:
    def __init__(self, topo: Topology, catalog: Catalog, *, sweep_interval: float = 60.0):
        self.topo = topo
        self.catalog = catalog
        self.sweep_interval = sweep_interval
        self.metrics = Metrics()
        self._next_sweep = sweep_interval

    def run(self, n_requests: int, *, arrival_rate: float = 200.0,
            region_skew: float | None = None, seed: int = 1) -> Metrics:
        stream = request_stream(self.catalog, n_requests, self.topo.regions,
                                arrival_rate=arrival_rate, region_skew=region_skew,
                                seed=seed)
        for t, region, obj in stream:
            if t >= self._next_sweep:
                for node in self.topo.all_caches():
                    node.cache.sweep(t)
                self._next_sweep += self.sweep_interval
            latency, source = self._serve(region, obj, t)
            self.metrics.record(source, obj.size, latency, obj.cacheable)
        return self.metrics

    def _serve(self, region: str, obj: Obj, now: float) -> tuple[float, str]:
        edge = self.topo.edge_for(region, obj.oid)
        latency, source = self._fetch(edge, obj, now)
        # add the client<->edge leg
        return self.topo.client_link.transfer_seconds(obj.size) + latency, source

    def _fetch(self, node: Node, obj: Obj, now: float) -> tuple[float, str]:
        """Return ``(latency_seconds, source_tier)`` to get ``obj`` at ``node``."""
        if node.tier == "origin":
            return node.uplink.transfer_seconds(obj.size), "origin"

        if obj.cacheable and node.cache.get(obj.oid, now) is not None:
            # served locally; cost is just this node's link to its child
            return 0.0, node.tier

        # miss -> ask the parent
        up_latency, source = self._fetch(node.parent, obj, now)
        hop = node.uplink.transfer_seconds(obj.size)
        if obj.cacheable:
            node.cache.put(obj.oid, obj.oid, obj.size, now, obj.ttl)
        return hop + up_latency, source


def compare_policies(regions, catalog_kwargs, run_kwargs, policies=None,
                     topo_kwargs=None) -> dict[str, dict]:
    policies = policies or ["fifo", "lru", "lfu", "s3fifo"]
    topo_kwargs = topo_kwargs or {}
    out = {}
    for p in policies:
        cat = Catalog(**catalog_kwargs)
        topo = Topology(regions, policy=p, **topo_kwargs)
        sim = Simulator(topo, cat)
        sim.run(**run_kwargs)
        out[p] = sim.metrics.summary()
    return out
