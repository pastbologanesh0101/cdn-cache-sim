"""Consistent hashing with virtual nodes.

Used to shard the object catalog across the edge caches inside one PoP, so
adding or removing an edge only reshuffles ``~1/N`` of the keys instead of all
of them.
"""

from __future__ import annotations

import bisect
import hashlib


def _hash(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


class HashRing:
    def __init__(self, nodes: list[str] | None = None, vnodes: int = 128):
        self.vnodes = vnodes
        self._ring: list[int] = []              # sorted hash positions
        self._owner: dict[int, str] = {}
        self._nodes: set[str] = set()
        for n in nodes or []:
            self.add(n)

    def add(self, node: str) -> None:
        if node in self._nodes:
            return
        self._nodes.add(node)
        for i in range(self.vnodes):
            h = _hash(f"{node}#{i}")
            bisect.insort(self._ring, h)
            self._owner[h] = node

    def remove(self, node: str) -> None:
        if node not in self._nodes:
            return
        self._nodes.discard(node)
        for i in range(self.vnodes):
            h = _hash(f"{node}#{i}")
            idx = bisect.bisect_left(self._ring, h)
            if idx < len(self._ring) and self._ring[idx] == h:
                self._ring.pop(idx)
            self._owner.pop(h, None)

    def get(self, key: str) -> str:
        if not self._ring:
            raise KeyError("empty ring")
        h = _hash(key)
        idx = bisect.bisect(self._ring, h) % len(self._ring)
        return self._owner[self._ring[idx]]

    @property
    def nodes(self) -> list[str]:
        return sorted(self._nodes)

    def distribution(self, keys: list[str]) -> dict[str, int]:
        counts = {n: 0 for n in self._nodes}
        for k in keys:
            counts[self.get(k)] += 1
        return counts
