"""Synthetic web workloads.

Real CDN traffic is heavy-tailed: a few objects get almost all the requests.
:class:`Catalog` draws object popularity from a **Zipf** distribution and gives
each object a size and (optionally) a TTL. :func:`request_stream` yields
``(time, region, object_id)`` events as a Poisson arrival process.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass
class Obj:
    oid: str
    size: int
    ttl: float | None
    cacheable: bool = True


class Catalog:
    def __init__(self, n_objects: int = 10_000, zipf_s: float = 0.9,
                 size_min: int = 4 * 1024, size_max: int = 4 * 1024 * 1024,
                 mean_ttl: float | None = 3600.0, uncacheable_frac: float = 0.02,
                 seed: int = 0):
        self.rng = random.Random(seed)
        self.n = n_objects
        self.zipf_s = zipf_s
        # precompute the Zipf CDF for fast sampling
        weights = [1.0 / (k ** zipf_s) for k in range(1, n_objects + 1)]
        total = sum(weights)
        self._cdf = []
        acc = 0.0
        for w in weights:
            acc += w / total
            self._cdf.append(acc)

        self.objects: list[Obj] = []
        for i in range(n_objects):
            size = int(math.exp(self.rng.uniform(math.log(size_min), math.log(size_max))))
            cacheable = self.rng.random() >= uncacheable_frac
            ttl = None
            if cacheable and mean_ttl:
                ttl = self.rng.expovariate(1.0 / mean_ttl)
            self.objects.append(Obj(f"obj{i}", size, ttl, cacheable))

    def sample(self) -> Obj:
        import bisect
        r = self.rng.random()
        return self.objects[bisect.bisect(self._cdf, r)]

    def by_id(self, oid: str) -> Obj:
        return self.objects[int(oid[3:])]

    def working_set_bytes(self, top_fraction: float = 0.1) -> int:
        k = max(1, int(self.n * top_fraction))
        return sum(o.size for o in self.objects[:k])


def request_stream(catalog: Catalog, n_requests: int, regions: list[str],
                   arrival_rate: float = 100.0, region_skew: float | None = None,
                   seed: int = 1):
    """Yield ``(t, region, Obj)``. ``arrival_rate`` is requests/second."""
    rng = random.Random(seed)
    if region_skew:
        rw = [1.0 / (k ** region_skew) for k in range(1, len(regions) + 1)]
        s = sum(rw)
        region_weights = [w / s for w in rw]
    else:
        region_weights = [1.0 / len(regions)] * len(regions)

    t = 0.0
    for _ in range(n_requests):
        t += rng.expovariate(arrival_rate)
        region = rng.choices(regions, weights=region_weights, k=1)[0]
        yield t, region, catalog.sample()
