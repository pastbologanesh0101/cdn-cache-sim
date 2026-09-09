# CDN Cache Simulator

**▶ Live demo: https://cdn-cache-sim-playground.vercel.app** — tune the workload (Zipf skew, catalog size, edge cache MB) in the browser and see hit ratio, origin offload and latency, compare eviction policies, or sweep cache size (runs on a Vercel Python function; code in [`web/`](web/)).

A trace-driven simulator for a **Content Delivery Network's cache hierarchy**.
It models realistic web traffic (Zipf popularity, heavy-tailed object sizes,
TTLs), shards the catalog across edge servers with **consistent hashing**, walks
each request up the **edge → regional → origin** tree filling caches on the way
back, and reports the numbers a CDN operator actually cares about: hit ratio,
**origin offload**, bandwidth saved, and latency percentiles. Pure Python, no
dependencies.

```
  clients (per region)
        │  Poisson arrivals, Zipf object popularity
        ▼
   ┌── edge PoP ──────────┐     consistent-hash ring shards objects
   │ edge-0  edge-1 ...    │     across the edges in the PoP
   └──────────┬───────────┘
              │ edge miss
        ┌── regional cache ──┐   one per region
        └──────────┬─────────┘
                   │ regional miss
              ┌── origin ──┐      always authoritative
              └────────────┘
```

## Quick start

```bash
git clone https://github.com/pastbologanesh0101/cdn-cache-sim
cd cdn-cache-sim
pip install -e ".[dev]"
pytest -q                                  # 29 tests

cdnsim run     --requests 100000 --policy s3fifo --edge-mb 64
cdnsim compare --requests 100000           # policies side by side
cdnsim sweep   --policy lru                 # hit ratio vs edge cache size
python examples/demo.py                      # policy / size / skew studies
```

```
$ cdnsim compare --requests 40000 --objects 8000
policy     overall_hit_ratio   edge_hit_ratio   origin_offload   bandwidth_saved   p99_ms
fifo                  0.5085           0.3326          0.5085            0.5163   432.46
lru                   0.5415           0.3735          0.5415            0.5454   429.62
lfu                   0.5815           0.4461          0.5815            0.5805   426.51
s3fifo                0.5714           0.4569          0.5714            0.5690   427.68
```

## Concepts demonstrated

| Area | Where | What it shows |
|---|---|---|
| **Cache eviction** | `cdnsim/cache.py` | Byte-bounded caches with **FIFO**, **LRU**, **LFU**, and **S3-FIFO** (SOSP'23 — small probation queue + main queue + ghost set; proven scan-resistant in a test). Plus `TTLCache`, a wrapper enforcing per-object expiry against the sim clock. |
| **Consistent hashing** | `cdnsim/hashring.py` | A hash ring with virtual nodes shards the catalog across the edges in a PoP. Tests show even distribution (±25% over 8 nodes) and that adding a node remaps only ~1/N of keys, removing one only its own. |
| **Workload modelling** | `cdnsim/workload.py` | Zipf popularity (the reason CDNs work at all), log-uniform object sizes, exponential TTLs, an uncacheable fraction, and a Poisson request stream with optional per-region skew. |
| **Cache hierarchy** | `cdnsim/topology.py`, `cdnsim/simulator.py` | edge → regional → origin, each hop a `Link(rtt, bandwidth)` so latency = `rtt + size·8/bandwidth`. Misses recurse upward; caches fill on the response path. Metrics split hits by tier. |
| **The offload question** | `cdnsim/simulator.py` | `origin_offload` and `bandwidth_saved` — how much traffic and bytes the CDN keeps off the origin — plus p50/p90/p99 latency, the metrics that justify a CDN's cost. |
| **Networking + systems** | end to end | Where the "networking" (topology, RTT, bandwidth, routing) meets the "systems" (cache replacement, sharding, memory budgets, TTL). |

## What the numbers say (from `examples/demo.py`)

- **Policy matters on Zipf traffic**: LFU / S3-FIFO beat LRU beat FIFO by ~10
  points of hit ratio at the same cache size.
- **Popularity skew dominates**: at a fixed 64 MB edge, moving Zipf `s` from
  0.6 → 1.4 takes the overall hit ratio from **0.16 → 0.92**.
- **Diminishing returns on size**: past the working set, doubling the edge
  cache barely moves offload — the capacity-planning sweet spot is visible in
  `cdnsim sweep`.
- A two-tier hierarchy can be **slightly non-monotonic** in edge size (a bigger
  edge changes what the regional tier sees) — a real effect the tests
  accommodate, while a single isolated cache stays strictly monotonic.

## Trace-driven, not discrete-event

Requests are processed in arrival order and each one's end-to-end latency is
computed from the hierarchy walk; virtual time advances with the arrival
stream. There is **no per-node queueing / contention model** — this simulator
answers "what is the hit ratio / offload / latency for this workload and
topology", not "what happens to tail latency when a PoP saturates". Adding an
event queue with service times at each node is the natural next step.

## Other limitations

- Single origin, one regional tier, tree topology (no anycast, no peering, no
  request collapsing / coalescing).
- Objects are immutable for their TTL; no revalidation (`If-None-Match`), no
  `stale-while-revalidate`.
- Sizes/latencies are modelled, not measured; the "bytes" are accounting only.

## Project layout

```
cdnsim/
  cache.py       FIFO / LRU / LFU / S3-FIFO (byte-bounded) + TTLCache
  hashring.py    consistent hash ring with virtual nodes
  workload.py    Zipf catalog + Poisson request stream
  topology.py    edge PoP (sharded) / regional / origin + Link model
  simulator.py   the hierarchy walk, Metrics (hit ratio, offload, latency pXX)
  cli.py         run / compare / sweep
examples/
  demo.py        policy vs size vs skew studies
tests/           cache / hashring / workload / simulator (hierarchy accounting,
                 TTL, monotonicity, S3-FIFO scan resistance)
```

## License

MIT
