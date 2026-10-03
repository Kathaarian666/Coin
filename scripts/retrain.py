"""Weekly retraining of the paper-test models (PROJE.md §0 D8), run in a research session (not on the server).

  python scripts/retrain.py <work dir>

1. research DB from the `veri` branch: daily parquet archive + the days the bot logged (robinhood/), a hole between
   them is downloaded from the chain (fomo_download.py + data_merge.py --fill); supplies and Pons launches
2. 5th-buyer moments (winner_study.py, 3 Sep on) and their holder features (transfer_download.py, transfer_features.py)
3. both models exported (paper_export.py, with its sklearn and live-feature parity checks) -> rhscanner/paper_model.json,
   rhscanner/paper_model_h.json
4. the fresh-day check of the new main model (fresh_test.py) for the report
Nothing is pushed or deployed: the session reviews the numbers, runs the tests, commits, and tells the user to update
the server (bash ~/Coin/deploy/install.sh; the paper test survives the restart).
"""

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
DAY_BLOCKS = 864_000


def run(*args, log: Path | None = None):
    print("$", " ".join(str(a) for a in args), flush=True)
    with open(log, "w") if log else open("/dev/null", "w") as out:
        res = subprocess.run([str(a) for a in args], cwd=ROOT, stdout=out if log else None, stderr=subprocess.STDOUT)
    if res.returncode:
        raise SystemExit(f"başarısız: {args[1]} (kod {res.returncode})" + (f", log {log}" if log else ""))


def main():
    work = Path(sys.argv[1])
    work.mkdir(parents=True, exist_ok=True)
    veri, db_path = work / "veri", work / "fomo.db"
    s = lambda *a: str(ROOT / "scripts" / a[0])  # noqa: E731

    # 1. data
    subprocess.run(["git", "fetch", "-q", "origin", "veri"], cwd=ROOT, check=True)
    if not veri.exists():
        subprocess.run(["git", "worktree", "add", "-q", "--detach", str(veri), "origin/veri"], cwd=ROOT, check=True)
    subprocess.run(["git", "checkout", "-q", "--detach", "origin/veri"], cwd=veri, check=True)
    if not db_path.exists():
        run(PY, s("data_import.py"), veri, db_path, log=work / "import.log")
    db = sqlite3.connect(db_path, timeout=300)
    last = db.execute("SELECT MAX(block), MAX(ts) FROM trades").fetchone()
    rh = sorted(p.name for p in (veri / "robinhood").iterdir()) if (veri / "robinhood").exists() else []
    if rh:  # a hole between the archive and the bot's first logged day is downloaded from the chain
        import csv
        import gzip
        with gzip.open(veri / "robinhood" / rh[0] / "trades.csv.gz", "rt") as f:
            first_bot = min(int(r["block"]) for r in csv.DictReader(f))
        if first_bot > last[0] + 1:
            days_ago = (time.time() - last[1]) / 86400
            run(PY, s("fomo_download.py"), round(days_ago + 0.05, 3), work / "hole.db", log=work / "hole.log")
            run(PY, s("data_merge.py"), work / "hole.db", db_path, "--fill", log=work / "merge.log")
        run(PY, s("solana_import.py"), veri, db_path, "--chain", "robinhood", log=work / "rh_import.log")
    run(PY, s("fomo_supply.py"), db_path, log=work / "supply.log")
    run(PY, s("pons_launches.py"), db_path, log=work / "launches.log")

    # 2. moments and holder features
    end = time.strftime("%Y-%m-%d %H:%M", time.gmtime(db.execute("SELECT MAX(ts) FROM trades").fetchone()[0]))
    winners, winners_h = work / "winners.parquet", work / "winners_h5.parquet"
    run(PY, s("winner_study.py"), db_path, winners, "2026-09-03", end, log=work / "winners.log")
    import pandas as pd
    pd.read_parquet(winners, columns=["coin", "k"]).query("k == 3")[["coin"]].drop_duplicates().to_parquet(work / "coins.parquet")
    run(PY, s("transfer_download.py"), db_path, work / "coins.parquet", 1, log=work / "transfers.log")
    run(PY, s("transfer_features.py"), db_path, winners, winners_h, 5, 1, log=work / "features.log")

    # 3. models (paper_export stops on any parity failure)
    run(PY, s("paper_export.py"), db_path, winners, log=work / "export.log")
    run(PY, s("paper_export.py"), db_path, winners_h, "--holder", log=work / "export_h.log")

    # 4. fresh-day check for the report: the new main model on the last 2 days
    for name in ("export.log", "export_h.log"):
        print(name, (work / name).read_text().strip().splitlines()[0], flush=True)
    print("Şimdi: python -m pytest -q, fresh_test.py ile son günler, commit + push; kullanıcıya sunucu güncellemesi.")


if __name__ == "__main__":
    main()
