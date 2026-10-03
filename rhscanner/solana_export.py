"""Nightly export of the collectors' data to the GitHub `veri` branch (PROJE.md §4.5, §4.5b): pump.fun
(rhscanner/solana.py) and, with --chain bnb, BNB Chain (rhscanner/bnb.py).

  python -m rhscanner.solana_export [<db>=solana.db] [--chain bnb]   every finished UTC day not exported yet
  python -m rhscanner.solana_export <db> --check                     only (re)writes solana/README.txt: tests the token
  python -m rhscanner.solana_export <db> --out <dir>                 writes the files to <dir>, no push

BNB per day: bnb/<day>/fomo_<hh>.csv.gz (6-hour parts), usdc_in.csv.gz, launches.csv.gz.

Per day: solana/<day>/trades_<hh>.csv.gz (four 6-hour parts, ~15 MB each), stats.csv.gz, sol_price.csv.gz; and
solana/pools.csv.gz, solana/mints.csv.gz (every pool / coin so far, with creators and creation times). The push uses VERI_GITHUB_TOKEN from .env (a fine-grained token with
Contents read/write on this repository only); it reaches git as an HTTP header through git's environment config,
never on a command line or in .git/config. The clone is shallow and without file contents (only the new files are
written), in a temporary folder that is deleted afterwards. A day is marked exported only after its push succeeded.
"""

import base64
import csv
import gzip
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from . import bnb, solana

log = logging.getLogger(__name__)

REPO = "https://github.com/Kathaarian666/Coin.git"
BRANCH = "veri"
PART_HOURS = 6
TRADE_COLS = ", ".join(solana.TRADE_COLS)
README = """Fomo'nun Solana işlemleri (pump.fun curve + PumpSwap), sunucudaki rhscanner/solana.py toplayıcısından.
Her gece rhscanner/solana_export.py ile gönderilir. Okumak için: scripts/solana_import.py.

<gün>/trades_<ss>.csv.gz  UTC ss:00'dan 6 saatlik işlemler: slot, ts, sig, venue (1 curve, 2 pumpswap), mint,
                          side (1 alım, 0 satış), user, lamports (SOL*1e9), tokens (ham, 6 ondalık), vsol, vtok
                          (curve: sanal rezervler; pumpswap: işlemden sonra havuzun SOL / coin rezervi), pool,
                          rsol, rtok (curve'ün gerçek rezervleri; rtok 0 = mezun; 3 Ekim öğleden önce boş)
<gün>/stats.csv.gz        dakikalık Fomo işlem sayıları: minute, total, curve, pumpswap, other
<gün>/sol_price.csv.gz    5 dakikada bir SOL/USD: ts, usd
pools.csv.gz              PumpSwap havuzları: pool, base (coin), quote, created_ts (havuzun kuruluşu = mezuniyet),
                          older_than (arama yarıda kaldıysa görülen en eski zaman; -1 bilinmiyor)
mints.csv.gz              coinler: mint, creator (geliştirici), first_seen (Fomo'da ilk görülme), created_ts
                          (oluşturulma), older_than, complete_ts (curve'ün boşaldığı ilk görülen işlem), curve (1:
                          Fomo'da curve'de görüldü = mezuniyetten önce)
"""


README_BNB = """Fomo'nun BNB Chain işlemleri ve flap.sh lansmanları, sunucudaki rhscanner/bnb.py toplayıcısından.
Her gece rhscanner/solana_export.py --chain bnb ile gönderilir. Okumak için: scripts/solana_import.py --chain bnb.

<gün>/fomo_<ss>.csv.gz    UTC ss:00'dan 6 saatlik Fomo olay ayakları: block, ts, tx, li, emitter (entry / executor),
                          src, dst, token, amount (ham birim); alım = executor -> kullanıcı, coin ayağı
<gün>/usdc_in.csv.gz      executor'a giden USDC transferleri (satış tutarı; USDC 18 ondalık): block, ts, tx, li, src,
                          amount
<gün>/launches.csv.gz     flap.sh TokenCreated: token, block, ts, creator, name, symbol
"""


def _day_bounds(day: str) -> tuple[int, int]:
    start = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    return start, start + 86400


def _write(path: Path, header: list[str], rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with gzip.open(path, "wt", newline="", compresslevel=9) as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
            n += 1
    return n


def pending_days(db: sqlite3.Connection, now: float, chain: str = "solana") -> list[str]:
    """Finished UTC days with trades that were not exported yet."""
    if chain == "bnb":
        db.executescript(bnb.SCHEMA)
        table = "fomo"
    else:
        solana.migrate(db)
        db.executescript(solana.SCHEMA)
        table = "trades"
    db.execute("CREATE TABLE IF NOT EXISTS exports (day TEXT PRIMARY KEY, ts INTEGER, rows INTEGER)")
    first = db.execute(f"SELECT MIN(ts) FROM {table} WHERE ts > 1600000000").fetchone()[0]
    if first is None:
        return []
    done = {d for (d,) in db.execute("SELECT day FROM exports")}
    out, t = [], int(first) // 86400 * 86400
    while t + 86400 <= now:
        day = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
        if day not in done:
            out.append(day)
        t += 86400
    return out


def write_bnb_day(db: sqlite3.Connection, day: str, root: Path) -> int:
    start, end = _day_bounds(day)
    folder = root / "bnb" / day
    cols = "block, ts, tx, li, emitter, src, dst, token, amount"
    rows = 0
    for h in range(0, 24, PART_HOURS):
        a, b = start + h * 3600, start + (h + PART_HOURS) * 3600
        rows += _write(folder / f"fomo_{h:02d}.csv.gz", cols.split(", "),
                       db.execute(f"SELECT {cols} FROM fomo WHERE ts >= ? AND ts < ? ORDER BY block, li", (a, b)))
    for table, cols in (("usdc_in", "block, ts, tx, li, src, amount"), ("launches", "token, block, ts, creator, name, symbol")):
        _write(folder / f"{table}.csv.gz", cols.split(", "),
               db.execute(f"SELECT {cols} FROM {table} WHERE ts >= ? AND ts < ? ORDER BY block", (start, end)))
    return rows


def write_day(db: sqlite3.Connection, day: str, root: Path, chain: str = "solana") -> int:
    if chain == "bnb":
        return write_bnb_day(db, day, root)
    start, end = _day_bounds(day)
    folder = root / "solana" / day
    rows = 0
    for h in range(0, 24, PART_HOURS):
        a, b = start + h * 3600, start + (h + PART_HOURS) * 3600
        rows += _write(folder / f"trades_{h:02d}.csv.gz", [c.strip() for c in TRADE_COLS.split(",")],
                       db.execute(f"SELECT {TRADE_COLS} FROM trades WHERE ts >= ? AND ts < ? ORDER BY slot", (a, b)))
    _write(folder / "stats.csv.gz", ["minute", "total", "curve", "pumpswap", "other"],
           db.execute("SELECT * FROM stats WHERE minute >= ? AND minute < ? ORDER BY minute", (start // 60, end // 60)))
    _write(folder / "sol_price.csv.gz", ["ts", "usd"],
           db.execute("SELECT * FROM sol_price WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end)))
    _write(root / "solana" / "pools.csv.gz", ["pool", "base", "quote", "created_ts", "older_than"],
           db.execute("SELECT pool, base, quote, created_ts, older_than FROM pools ORDER BY pool"))
    _write(root / "solana" / "mints.csv.gz", ["mint", "creator", "first_seen", "created_ts", "older_than", "complete_ts",
                                               "curve"],
           db.execute("SELECT mint, creator, first_seen, created_ts, older_than, complete_ts, curve FROM mints ORDER BY mint"))
    return rows


def _git_env(token: str) -> dict:
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {auth}"}


def _git(env, *args, cwd=None):
    res = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if res.returncode:
        raise RuntimeError(f"git {args[0]}: {res.stderr.strip()[-300:]}")
    return res.stdout


def push(files_root: Path, message: str, token: str, repo: str = REPO, tries: int = 3):
    """Adds everything under files_root to the branch (other files stay as they are) and pushes."""
    env = _git_env(token)
    for attempt in range(tries):
        work = Path(tempfile.mkdtemp(prefix="veri-"))
        try:
            _git(env, "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", "-b", BRANCH, repo,
                 str(work))
            _git(env, "reset", "-q", cwd=work)  # index = the branch's files, none of them downloaded
            shutil.copytree(files_root, work, dirs_exist_ok=True)
            # only the new files: the branch's other files are missing on disk and must not be staged as deleted
            new = [str(p.relative_to(files_root)) for p in files_root.rglob("*") if p.is_file()]
            _git(env, "add", "--", *new, cwd=work)
            if not _git(env, "diff", "--cached", "--name-only", cwd=work).strip():
                return
            _git(env, "-c", "user.name=fomo-bot", "-c", "user.email=fomo-bot@users.noreply.github.com",
                 "commit", "-q", "-m", message, cwd=work)
            _git(env, "push", "-q", "origin", f"HEAD:{BRANCH}", cwd=work)
            return
        except RuntimeError as exc:
            if attempt == tries - 1:
                raise
            log.warning("push failed (%s); trying again", exc)
            time.sleep(10 * (attempt + 1))
        finally:
            shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    out = Path(argv.pop(argv.index("--out") + 1)) if "--out" in argv else None
    check = "--check" in argv
    chain = argv.pop(argv.index("--chain") + 1) if "--chain" in argv else "solana"
    readme = README_BNB if chain == "bnb" else README
    args = [a for a in argv if not a.startswith("--")]
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    token = os.environ.get("VERI_GITHUB_TOKEN", "").strip()
    if out is None and not token:
        log.error("VERI_GITHUB_TOKEN yok: .env dosyasına eklenmeli (PROJE.md §4.5)")
        return 1
    db = sqlite3.connect(args[0] if args else "solana.db", timeout=120)
    if check:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "solana").mkdir()
            (Path(tmp) / "solana" / "README.txt").write_text(README)
            push(Path(tmp), "solana: README", token)
        log.info("token çalışıyor: veri dalına yazılabildi")
        return 0
    for day in pending_days(db, time.time(), chain):
        if out is not None:
            log.info("%s: %d işlem -> %s", day, write_day(db, day, out, chain), out)
            continue
        with tempfile.TemporaryDirectory() as tmp:
            rows = write_day(db, day, Path(tmp), chain)
            (Path(tmp) / chain / "README.txt").write_text(readme)
            push(Path(tmp), f"{chain} {day}: {rows} kayıt", token)
        db.execute("INSERT OR REPLACE INTO exports VALUES (?, ?, ?)", (day, int(time.time()), rows))
        db.commit()
        log.info("%s gönderildi: %d işlem", day, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
