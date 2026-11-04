from bot.data.candles import CandleBuilder


def test_5m_bucketing_and_close():
    closed = []
    cb = CandleBuilder("X", 5, on_close=closed.append)
    base = 9 * 3600_000  # arbitrary ms aligned
    # three ticks in first 5m bucket
    cb.add_tick(base + 0, 100.0, 10)
    cb.add_tick(base + 60_000, 102.0, 5)
    cb.add_tick(base + 120_000, 101.0, 5)
    # tick in next bucket -> closes first
    cb.add_tick(base + 5 * 60_000 + 1000, 105.0, 7)

    assert len(closed) == 1
    c = closed[0]
    assert c.open == 100.0
    assert c.high == 102.0
    assert c.low == 100.0
    assert c.close == 101.0
    assert c.volume == 20
    assert c.closed is True


def test_force_close():
    cb = CandleBuilder("X", 15)
    cb.add_tick(0, 50.0)
    cb.force_close()
    assert cb.last_closed is not None
    assert cb.last_closed.close == 50.0
