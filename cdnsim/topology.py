"""The CDN hierarchy: clients -> edge PoP (sharded) -> regional cache -> origin.

Links carry a latency and a bandwidth; the time to move an object across a link
is ``rtt + size*8 / bandwidth``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cache import TTLCache, make_cache
from .hashring import HashRing


@dataclass
class Link:
    rtt_ms: float
    bandwidth_mbps: float

    def transfer_seconds(self, size_bytes: int) -> float:
        return self.rtt_ms / 1000.0 + (size_bytes * 8) / (self.bandwidth_mbps * 1e6)


class Node:
    def __init__(self, name: str, tier: str, policy: str, capacity_bytes: int,
                 uplink: Link, parent: "Node | None"):
        self.name = name
        self.tier = tier                       # "edge" | "regional" | "origin"
        self.parent = parent
        self.uplink = uplink                   # link to the parent
        self.cache = None if tier == "origin" else TTLCache(
            make_cache(policy, capacity_bytes))

    @property
    def capacity(self) -> int:
        return 0 if self.cache is None else self.cache.inner.capacity


class Topology:
    """A regional tree. One PoP per region; each PoP has ``edges_per_pop`` edge
    servers behind a consistent-hash ring; each PoP has one regional parent; all
    regionals share one origin."""

    def __init__(self, regions: list[str], *, policy: str = "lru",
                 edges_per_pop: int = 2, edge_capacity: int = 64 * 1024 * 1024,
                 regional_capacity: int = 512 * 1024 * 1024,
                 client_link=Link(10, 100), edge_link=Link(20, 1000),
                 regional_link=Link(40, 10_000)):
        self.regions = regions
        self.client_link = client_link
        self.origin = Node("origin", "origin", policy, 1, regional_link, None)

        self.regionals: dict[str, Node] = {}
        self.pops: dict[str, list[Node]] = {}
        self.rings: dict[str, HashRing] = {}
        for r in regions:
            reg = Node(f"regional-{r}", "regional", policy, regional_capacity,
                       regional_link, self.origin)
            self.regionals[r] = reg
            edges = [Node(f"edge-{r}-{i}", "edge", policy, edge_capacity,
                          edge_link, reg) for i in range(edges_per_pop)]
            self.pops[r] = edges
            self.rings[r] = HashRing([e.name for e in edges])

    def edge_for(self, region: str, oid: str) -> Node:
        edge_name = self.rings[region].get(oid)
        return next(e for e in self.pops[region] if e.name == edge_name)

    def all_caches(self):
        for edges in self.pops.values():
            yield from edges
        yield from self.regionals.values()

    def total_capacity(self) -> int:
        return sum(n.capacity for n in self.all_caches())
