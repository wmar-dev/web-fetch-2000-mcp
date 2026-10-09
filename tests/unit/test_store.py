import sqlite3

from webfetch2000.store import SCHEMA_VERSION, Store


def test_creates_schema_and_wal(data_dir):
    store = Store.open(data_dir / "w.db")
    assert store.available and store.error is None
    with store.conn() as c:
        mode = c.execute("PRAGMA journal_mode").fetchone()[0]
        tables = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
        ver = c.execute("select value from meta where key='schema_version'").fetchone()[0]
    assert mode.lower() == "wal"
    assert {"outcomes", "cache", "meta"} <= tables
    assert int(ver) == SCHEMA_VERSION


def test_reopen_preserves_data(data_dir):
    p = data_dir / "w.db"
    s1 = Store.open(p)
    with s1.conn() as c:
        c.execute("insert into meta(key, value) values ('k', 'v')")
    s2 = Store.open(p)
    with s2.conn() as c:
        assert c.execute("select value from meta where key='k'").fetchone()[0] == "v"


def test_migrates_old_schema(data_dir):
    p = data_dir / "old.db"
    raw = sqlite3.connect(p)
    raw.execute("create table meta (key text primary key, value text)")
    raw.execute("insert into meta values ('schema_version', '0')")
    raw.commit()
    raw.close()
    store = Store.open(p)
    assert store.available
    with store.conn() as c:
        assert (
            int(c.execute("select value from meta where key='schema_version'").fetchone()[0])
            == SCHEMA_VERSION
        )
        c.execute("select * from outcomes limit 1")


def test_corrupted_file_is_unavailable_not_crash(data_dir):
    p = data_dir / "bad.db"
    p.write_bytes(b"this is definitely not a sqlite database" * 100)
    store = Store.open(p)
    assert not store.available
    assert store.error


def test_unwritable_location_is_unavailable(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    store = Store.open(blocker / "sub" / "w.db")
    assert not store.available and store.error


def test_conn_on_unavailable_store_raises(tmp_path):
    import pytest

    from webfetch2000.store import StoreUnavailable

    blocker = tmp_path / "file"
    blocker.write_text("x")
    store = Store.open(blocker / "w.db")
    with pytest.raises(StoreUnavailable):
        with store.conn():
            pass


def test_none_path_gives_unavailable():
    store = Store.unavailable("disabled")
    assert not store.available and store.error == "disabled"


def test_store_files_are_owner_only(tmp_path):
    import os
    import stat
    import sys

    if sys.platform == "win32":
        return
    store = Store.open(tmp_path / "fresh" / "w.db")
    with store.conn() as c:
        c.execute("insert into meta(key, value) values ('k', 'v')")
    assert stat.S_IMODE(os.stat(tmp_path / "fresh" / "w.db").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "fresh").st_mode) == 0o700
