import sqlite3
import subprocess

from rhscanner import solana, solana_export


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _db(path):
    db = sqlite3.connect(path)
    db.executescript(solana.SCHEMA)
    day = 1_759_449_600  # 2025-10-03 00:00 UTC
    db.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   [(1, day + 60, "s1", 1, "M", 1, "U", 1e9, 1e12, 3e10, 1e15, None, 0.0, 7e14),
                    (2, day + 7 * 3600, "s2", 2, "M", 0, "U", 5e8, 1e11, 9e10, 2e14, "P", None, None),
                    (3, day + 86400 + 5, "s3", 1, "M", 1, "U", 1.0, 1.0, 1.0, 1.0, None, 1.0, 1.0)])
    db.execute("INSERT INTO pools VALUES ('P', 'M', 'W', 123, NULL)")
    db.execute("INSERT INTO mints VALUES ('M', 'C', 5, 4, NULL, 99, 1)")
    db.commit()
    return db, day


def test_pending_days_skips_today_and_exported(tmp_path):
    db, day = _db(tmp_path / "s.db")
    assert solana_export.pending_days(db, day + 86400 + 100) == ["2025-10-03"]
    assert solana_export.pending_days(db, day + 2 * 86400) == ["2025-10-03", "2025-10-04"]
    db.execute("INSERT INTO exports VALUES ('2025-10-03', 0, 2)")
    assert solana_export.pending_days(db, day + 2 * 86400) == ["2025-10-04"]


def test_push_adds_files_and_keeps_the_rest(tmp_path, monkeypatch):
    remote, seed = tmp_path / "remote.git", tmp_path / "seed"
    _git("init", "-q", "--bare", "-b", "veri", str(remote))
    _git("-C", str(remote), "config", "uploadpack.allowFilter", "true")
    _git("init", "-q", "-b", "veri", str(seed))
    (seed / "2025-09-30.parquet").write_bytes(b"x" * 1000)
    (seed / "solana").mkdir()
    (seed / "solana" / "old.txt").write_text("old")
    _git("add", ".", cwd=seed)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed", cwd=seed)
    _git("push", "-q", str(remote), "veri", cwd=seed)

    db, _ = _db(tmp_path / "s.db")
    out = tmp_path / "out"
    assert solana_export.write_day(db, "2025-10-03", out) == 2
    solana_export.push(out, "solana test", "tok", repo=f"file://{remote}")
    files = set(_git("-C", str(remote), "ls-tree", "-r", "--name-only", "veri").split())
    assert {"2025-09-30.parquet", "solana/old.txt", "solana/pools.csv.gz", "solana/2025-10-03/trades_00.csv.gz",
            "solana/2025-10-03/trades_06.csv.gz", "solana/2025-10-03/stats.csv.gz"} <= files
    # nothing new -> no extra commit
    n = _git("-C", str(remote), "rev-list", "--count", "veri")
    solana_export.push(out, "again", "tok", repo=f"file://{remote}")
    assert _git("-C", str(remote), "rev-list", "--count", "veri") == n


def test_import_reads_the_export_back(tmp_path):
    import importlib.util
    import sys
    from pathlib import Path

    db, _ = _db(tmp_path / "s.db")
    solana_export.write_day(db, "2025-10-03", tmp_path / "veri")
    spec = importlib.util.spec_from_file_location("solana_import", Path(__file__).parents[1] / "scripts" / "solana_import.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkey = [None, str(tmp_path / "veri"), str(tmp_path / "r.db")]
    old, sys.argv = sys.argv, monkey
    try:
        mod.main()
        mod.main()  # second run skips the day
    finally:
        sys.argv = old
    r = sqlite3.connect(tmp_path / "r.db")
    assert r.execute("SELECT * FROM trades ORDER BY slot").fetchall() == \
        db.execute("SELECT * FROM trades WHERE slot < 3 ORDER BY slot").fetchall()
    assert r.execute("SELECT * FROM pools").fetchall() == [("P", "M", "W", 123, None)]
    assert r.execute("SELECT * FROM mints").fetchall() == [("M", "C", 5, 4, None, 99, 1)]


def test_robinhood_days_from_the_bot_reach_the_research_db(tmp_path):
    import asyncio
    import importlib.util
    import sys
    from pathlib import Path

    from rhscanner.bot import ScannerApp
    from rhscanner.config import Settings
    from rhscanner.fomo import FomoTrade

    app = ScannerApp(Settings(db_path=str(tmp_path / "r.db")))
    app.paper_model = None  # only the logging matters here
    day = 1_759_449_600
    tok = "0x" + "AB" * 20
    trades = [FomoTrade("0x1", 100, tok, "buy", "0x" + "a" * 40, 50.0, day + 10, 10**21),
              FomoTrade("0x2", 101, tok, "sell", "0x" + "b" * 40, 20.0, day + 10, 5 * 10**20)]
    asyncio.run(app.on_fomo_trades(trades))
    asyncio.run(app.on_fomo_trades(trades))  # replayed after a restart: no twins
    db = app.storage.db
    assert db.execute("SELECT COUNT(*) FROM fomo_log").fetchone()[0] == 2
    assert solana_export.pending_days(db, day + 86400 + 5, "robinhood") == ["2025-10-03"]
    assert solana_export.write_day(db, "2025-10-03", tmp_path / "veri", "robinhood") == 2

    research = sqlite3.connect(tmp_path / "fomo.db")
    research.executescript("""CREATE TABLE trades (block INTEGER, ts REAL, token INTEGER, side INTEGER, trader INTEGER,
                              usd REAL, amount REAL);
                              CREATE TABLE names (id INTEGER PRIMARY KEY, kind TEXT, addr TEXT, UNIQUE (kind, addr));""")
    research.execute("INSERT INTO names VALUES (1, 'token', ?)", ("0x" + "Ab" * 20,))  # known coin, other case
    research.execute("INSERT INTO trades VALUES (100, 1.0, 1, 1, 1, 9.0, 1.0)")  # block 100 already there
    research.commit()
    spec = importlib.util.spec_from_file_location("solana_import", Path(__file__).parents[1] / "scripts" / "solana_import.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old, sys.argv = sys.argv, [None, str(tmp_path / "veri"), str(tmp_path / "fomo.db"), "--chain", "robinhood"]
    try:
        mod.main()
    finally:
        sys.argv = old
    r = sqlite3.connect(tmp_path / "fomo.db")
    assert r.execute("SELECT block, token, side, usd, amount FROM trades ORDER BY block").fetchall() == \
        [(100, 1, 1, 9.0, 1.0), (101, 1, 0, 20.0, 5e20)]
    asyncio.run(app.rpc.close())
