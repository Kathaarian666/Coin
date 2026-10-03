import sqlite3
import subprocess

from rhscanner import solana, solana_export


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _db(path):
    db = sqlite3.connect(path)
    db.executescript(solana.SCHEMA)
    day = 1_759_449_600  # 2025-10-03 00:00 UTC
    db.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   [(1, day + 60, "s1", 1, "M", 1, "U", 1e9, 1e12, 3e10, 1e15, None),
                    (2, day + 7 * 3600, "s2", 2, "M", 0, "U", 5e8, 1e11, None, None, "P"),
                    (3, day + 86400 + 5, "s3", 1, "M", 1, "U", 1.0, 1.0, 1.0, 1.0, None)])
    db.execute("INSERT INTO pools VALUES ('P', 'M', 'W')")
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
    assert r.execute("SELECT * FROM pools").fetchall() == [("P", "M", "W")]
