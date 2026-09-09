from cdnsim.hashring import HashRing


KEYS = [f"obj{i}" for i in range(20_000)]


def test_distribution_is_roughly_even():
    ring = HashRing([f"edge{i}" for i in range(8)], vnodes=200)
    dist = ring.distribution(KEYS)
    lo, hi = min(dist.values()), max(dist.values())
    mean = len(KEYS) / 8
    assert hi / mean < 1.25 and lo / mean > 0.75      # within +/-25%


def test_lookup_is_stable():
    ring = HashRing(["a", "b", "c"])
    first = {k: ring.get(k) for k in KEYS[:1000]}
    for k, v in first.items():
        assert ring.get(k) == v


def test_adding_a_node_moves_about_one_over_n_keys():
    ring = HashRing([f"edge{i}" for i in range(4)], vnodes=200)
    before = {k: ring.get(k) for k in KEYS}
    ring.add("edge4")
    moved = sum(1 for k in KEYS if ring.get(k) != before[k])
    frac = moved / len(KEYS)
    # ideal is 1/5 = 0.2; consistent hashing keeps it close, definitely << 1
    assert 0.12 < frac < 0.30


def test_removing_a_node_only_moves_its_keys():
    ring = HashRing([f"edge{i}" for i in range(5)], vnodes=200)
    before = {k: ring.get(k) for k in KEYS}
    owned_by_2 = {k for k, v in before.items() if v == "edge2"}
    ring.remove("edge2")
    for k in KEYS:
        if k not in owned_by_2:
            assert ring.get(k) == before[k]           # untouched
    assert all(ring.get(k) != "edge2" for k in owned_by_2)


def test_empty_ring_raises():
    import pytest
    with pytest.raises(KeyError):
        HashRing().get("x")
