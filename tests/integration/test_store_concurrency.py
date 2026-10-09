"""Several processes recording outcomes into the shared store lose nothing (FR-022, SC-010)."""

import multiprocessing as mp

from webfetch2000.config import Settings
from webfetch2000.memory import Memory
from webfetch2000.store import Store

PROCS = 5
PER_PROC = 40


def _worker(db_path: str, idx: int) -> None:
    from pathlib import Path

    store = Store.open(Path(db_path))
    mem = Memory(store, Settings())
    for i in range(PER_PROC):
        mem.record("shared.com", "/a/b", "http", i % 2 == 0, 10)


def test_concurrent_instances_lose_no_outcomes(data_dir):
    db = data_dir / "shared.db"
    Store.open(db)  # create schema first
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_worker, args=(str(db), i)) for i in range(PROCS)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    store = Store.open(db)
    with store.conn() as c:
        rows = c.execute(
            "select path_prefix, observations, successes, failures from outcomes "
            "where domain='shared.com' and strategy='http' order by path_prefix"
        ).fetchall()
        integrity = c.execute("pragma integrity_check").fetchone()[0]
    assert integrity == "ok"
    assert [r[0] for r in rows] == ["", "/a"]
    total = PROCS * PER_PROC
    for _, obs, succ, fail in rows:
        assert obs == total  # SC-010: 100% of recorded outcomes present
        assert succ + fail == __import__("pytest").approx(total, abs=0.5)  # negligible decay
        assert abs(succ - fail) < 1.0
