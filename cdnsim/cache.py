"""Size-bounded caches with pluggable eviction.

A cache holds objects keyed by id, each with a byte size. Capacity is in bytes.
``get`` returns the value or ``None``; ``put`` inserts and evicts until the
cache fits. Policies: FIFO, LRU, LFU, and **S3-FIFO** (a modern
scan-resistant policy: a small FIFO probation queue, a larger FIFO main queue,
and a ghost set of recently-evicted keys).

Optional per-object TTL is handled by :class:`TTLCache`, a thin wrapper that
drops expired entries on access and on a periodic sweep.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import OrderedDict, deque
from dataclasses import dataclass, field


@dataclass
class Stats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    admitted_bytes: int = 0
    evicted_bytes: int = 0

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_ratio(self) -> float:
        return self.hits / self.lookups if self.lookups else 0.0


class Cache(ABC):
    def __init__(self, capacity_bytes: int):
        if capacity_bytes <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity_bytes
        self.used = 0
        self.stats = Stats()
        self._store: dict = {}          # key -> value
        self._size: dict = {}           # key -> bytes

    def __contains__(self, key) -> bool:
        return key in self._store

    def __len__(self) -> int:
        return len(self._store)

    def get(self, key):
        if key in self._store:
            self.stats.hits += 1
            self._on_hit(key)
            return self._store[key]
        self.stats.misses += 1
        return None

    def put(self, key, value, size: int) -> None:
        if size > self.capacity:
            return                      # never cacheable
        if key in self._store:
            self._store[key] = value
            self._on_hit(key)
            return
        self._store[key] = value
        self._size[key] = size
        self.used += size
        self.stats.admitted_bytes += size
        self._on_insert(key)
        while self.used > self.capacity:
            victim = self._choose_victim()
            self._remove(victim, evicted=True)

    def _remove(self, key, *, evicted: bool) -> None:
        sz = self._size.pop(key)
        self._store.pop(key, None)
        self.used -= sz
        self._on_remove(key)
        if evicted:
            self.stats.evictions += 1
            self.stats.evicted_bytes += sz

    # -- policy hooks --------------------------------------
    @abstractmethod
    def _on_insert(self, key) -> None: ...

    @abstractmethod
    def _on_hit(self, key) -> None: ...

    @abstractmethod
    def _on_remove(self, key) -> None: ...

    @abstractmethod
    def _choose_victim(self): ...


class FIFOCache(Cache):
    name = "fifo"

    def __init__(self, capacity_bytes: int):
        super().__init__(capacity_bytes)
        self._order: deque = deque()

    def _on_insert(self, key):
        self._order.append(key)

    def _on_hit(self, key):
        pass

    def _on_remove(self, key):
        try:
            self._order.remove(key)
        except ValueError:
            pass

    def _choose_victim(self):
        return self._order[0]


class LRUCache(Cache):
    name = "lru"

    def __init__(self, capacity_bytes: int):
        super().__init__(capacity_bytes)
        self._order: OrderedDict = OrderedDict()

    def _on_insert(self, key):
        self._order[key] = None

    def _on_hit(self, key):
        self._order.move_to_end(key)

    def _on_remove(self, key):
        self._order.pop(key, None)

    def _choose_victim(self):
        return next(iter(self._order))


class LFUCache(Cache):
    name = "lfu"

    def __init__(self, capacity_bytes: int):
        super().__init__(capacity_bytes)
        self._freq: dict = {}
        self._tick = 0                  # tiebreak: evict least-recently among equal freq

    def _on_insert(self, key):
        self._tick += 1
        self._freq[key] = (1, self._tick)

    def _on_hit(self, key):
        self._tick += 1
        f, _ = self._freq[key]
        self._freq[key] = (f + 1, self._tick)

    def _on_remove(self, key):
        self._freq.pop(key, None)

    def _choose_victim(self):
        return min(self._freq, key=lambda k: self._freq[k])


class S3FIFOCache(Cache):
    """S3-FIFO (Yang et al., SOSP'23): a small probation FIFO (S), a large main
    FIFO (M), and a ghost set (G) of keys evicted from S.

    * insert: a key seen recently (in G) goes straight to M; otherwise to S.
    * hit: bump a small (0..3) frequency counter.
    * evict from S: if the head was hit at least once, move it to M (freeing
      nothing yet); otherwise send it to the ghost set and drop it.
    * evict from M: give hit objects a second chance (decrement, requeue);
      otherwise drop.

    The one-hit-wonder scan stays confined to S, so hot objects promoted to M
    survive it.
    """

    name = "s3fifo"

    def __init__(self, capacity_bytes: int, small_ratio: float = 0.1):
        super().__init__(capacity_bytes)
        self._small_cap = max(1, int(capacity_bytes * small_ratio))
        self._S: deque = deque()
        self._M: deque = deque()
        self._G: OrderedDict = OrderedDict()
        self._in_small: set = set()
        self._freq: dict = {}
        self._small_used = 0

    def _on_insert(self, key):
        self._freq[key] = 0
        if key in self._G:
            del self._G[key]
            self._M.append(key)
        else:
            self._S.append(key)
            self._in_small.add(key)
            self._small_used += self._size[key]

    def _on_hit(self, key):
        self._freq[key] = min(3, self._freq.get(key, 0) + 1)

    def _on_remove(self, key):
        self._freq.pop(key, None)
        if key in self._in_small:
            self._in_small.discard(key)
            self._small_used -= self._size.get(key, 0)
            try:
                self._S.remove(key)
            except ValueError:
                pass
        else:
            try:
                self._M.remove(key)
            except ValueError:
                pass

    def _promote_to_main(self, key):
        self._S.popleft()
        self._in_small.discard(key)
        self._small_used -= self._size[key]
        self._M.append(key)                 # keep its freq: it earns second chances in M

    def _trim_ghost(self):
        cap = max(8, len(self._store))
        while len(self._G) > cap:
            self._G.popitem(last=False)

    def _choose_victim(self):
        # S full  -> evict from S (objects hit 2+ times graduate to M instead)
        # S not full -> evict from M (hit objects get a decrementing second chance)
        # These branches never chain, so an object just promoted into M is not
        # immediately re-evaluated -- that is what makes S3-FIFO scan-resistant.
        if self._small_used >= self._small_cap and self._S:
            while self._S:
                key = self._S[0]
                if self._freq.get(key, 0) > 1:
                    self._promote_to_main(key)
                    continue
                self._S.popleft()
                self._in_small.discard(key)
                self._small_used -= self._size[key]
                self._G[key] = None
                self._trim_ghost()
                return key
        while self._M:
            key = self._M[0]
            if self._freq.get(key, 0) > 0:
                self._M.popleft()
                self._freq[key] -= 1
                self._M.append(key)
                continue
            return key
        return self._S[0]                   # last resort: strict FIFO on S


REGISTRY = {c.name: c for c in (FIFOCache, LRUCache, LFUCache, S3FIFOCache)}


def make_cache(name: str, capacity_bytes: int) -> Cache:
    try:
        return REGISTRY[name](capacity_bytes)
    except KeyError:
        raise ValueError(f"unknown cache policy {name!r}; choose {sorted(REGISTRY)}")


class TTLCache:
    """Wraps any :class:`Cache` and enforces per-entry expiry using an external
    clock (the simulator's virtual time)."""

    def __init__(self, inner: Cache):
        self.inner = inner
        self._expiry: dict = {}

    def get(self, key, now: float):
        exp = self._expiry.get(key)
        if exp is not None and exp <= now:
            self._evict_expired(key)
            self.inner.stats.misses += 1
            return None
        return self.inner.get(key)

    def put(self, key, value, size: int, now: float, ttl: float | None) -> None:
        self.inner.put(key, value, size)
        if ttl is not None and key in self.inner:
            self._expiry[key] = now + ttl
        else:
            self._expiry.pop(key, None)

    def sweep(self, now: float) -> int:
        dead = [k for k, e in self._expiry.items() if e <= now]
        for k in dead:
            self._evict_expired(k)
        return len(dead)

    def _evict_expired(self, key) -> None:
        if key in self.inner:
            self.inner._remove(key, evicted=True)
        self._expiry.pop(key, None)

    @property
    def stats(self) -> Stats:
        return self.inner.stats

    def __contains__(self, key):
        return key in self.inner

    def __len__(self):
        return len(self.inner)
