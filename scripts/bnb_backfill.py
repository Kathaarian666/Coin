"""BNB picks' real pool depth and exits, looked up afterwards (PROJE.md §4.17): the same raw data the collector's watch
records live (rhscanner/bnb.py coin_xfer / venue_logs), for the 3-25 Oct picks, from an archive node. Runs on the
server (the research session has no BNB access); needs BSC_RPC_URL in .env (a free dRPC key: public free nodes do not
serve old logs). Resumable; pushes its output to the `veri` branch (arastirma/bnb-geri/) when done.

  .venv/bin/python scripts/bnb_backfill.py [research/bnb_backfill_jobs.csv] [--no-push]

jobs: coin, ts (alert), first_block, alert_block, t5 (the Fomo 5x time, NaN = none), hit_block, end_block (alert +
3 h 20 min). Per coin:
- every Transfer of the coin from alert_block - 200 to end_block -> coin_xfer.jsonl [coin, block, tx, li, src, dst, amount]
- the receipts of the coin's transactions at these moments: the first at / after the alert, after the 5x and 10 min
  later, the last before end_block, and one every SAMPLE_S in between -> venue_logs.jsonl [coin, block, tx, li,
  address, topics, data] (Fomo's own logs left out); decoded in the research
"""

import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rhscanner import bnb  # noqa: E402

CHUNK = 5000  # blocks per eth_getLogs (the free plan's range limit)
SAMPLE_S = 300
BPS = 2.22  # BNB blocks per s (0.45 s blocks, from the Fomo trades of 3-25 Oct)
FOMO = {bnb.FOMO_ENTRY, bnb.FOMO_EXECUTOR, bnb.FOMO_ENTRY_2, bnb.FOMO_EXECUTOR_2}


def env_url() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("BSC_RPC_URL="):
            return line.split("=", 1)[1].strip()
    return os.environ["BSC_RPC_URL"]


def rpc(url, method, params):
    err = None
    for i in range(8):
        try:
            req = urllib.request.Request(url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                          "params": params}).encode(),
                                         {"content-type": "application/json", "user-agent": "curl/8.0"})
            res = json.load(urllib.request.urlopen(req, timeout=60))
            if "error" in res:
                raise RuntimeError(str(res["error"])[:200])
            return res["result"]
        except Exception as exc:
            err = exc
            if any(w in str(exc).lower() for w in ("range", "too many", "exceed", "10000")) and "rate" not in str(exc).lower():
                raise RuntimeError(f"range: {exc}")  # transfers() splits the range
            time.sleep(min(30, 2 ** i))
    raise RuntimeError(f"{method} failed: {err}")


def logs(url, coin, lo, hi):
    """eth_getLogs over [lo, hi], halving the range when the node refuses it."""
    try:
        return rpc(url, "eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi), "address": coin,
                                         "topics": [bnb.TRANSFER]}])
    except RuntimeError as exc:
        if not str(exc).startswith("range") or hi - lo < 10:
            raise
        mid = (lo + hi) // 2
        return logs(url, coin, lo, mid) + logs(url, coin, mid + 1, hi)


def transfers(url, coin, lo, hi):
    out = []
    for a in range(lo, hi + 1, CHUNK):
        for e in logs(url, coin, a, min(hi, a + CHUNK - 1)):
            if len(e["topics"]) < 3:
                continue
            out.append([coin, int(e["blockNumber"], 16), e["transactionHash"], int(e["logIndex"], 16),
                        bnb._addr(e["topics"][1]), bnb._addr(e["topics"][2]),
                        str(int(e["data"], 16)) if e["data"] not in ("0x", "") else "0"])
    return sorted(out, key=lambda x: (x[1], x[3]))


def chosen_txs(xfer, job):
    """The transactions whose receipts are read (see the module doc)."""
    blocks = [(x[1], x[2]) for x in xfer if x[1] >= job["alert_block"]]
    if not blocks:
        return []
    marks = [job["alert_block"], job["end_block"]]
    if job["hit_block"] > 0:
        marks += [job["hit_block"], job["hit_block"] + int(600 * BPS)]
    marks += list(range(job["alert_block"], job["end_block"], int(SAMPLE_S * BPS)))
    out = set()
    for m in marks:
        after = [t for b, t in blocks if b >= m]
        out.add(after[0] if after and m != job["end_block"] else [t for b, t in blocks if b <= m][-1])
    return sorted(out)


PART_LINES = 200_000  # ~10-20 MB gzipped


def write_parts(src: Path, dest: Path, name: str) -> int:
    """src (jsonl) as dest/<name>_00.jsonl.gz, _01, ... of PART_LINES lines each; returns the number of parts."""
    import gzip
    part, n, f = 0, 0, None
    with open(src) as lines:
        for line in lines:
            if f is None or n == PART_LINES:
                if f:
                    f.close()
                    part += 1
                f, n = gzip.open(dest / f"{name}_{part:02d}.jsonl.gz", "wt"), 0
            f.write(line)
            n += 1
    if f:
        f.close()
        part += 1
    return part


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    jobs_path = Path(args[0] if args else ROOT / "research" / "bnb_backfill_jobs.csv")
    out = ROOT / "bnb_geri"
    out.mkdir(exist_ok=True)
    url = env_url()
    head = jobs_path.read_text().splitlines()
    cols = head[0].split(",")
    jobs = [dict(zip(cols, line.split(","))) for line in head[1:]]
    done = set()
    if (out / "done.txt").exists():
        done = set((out / "done.txt").read_text().split())
    t0 = time.time()
    for n, j in enumerate(jobs):
        if j["coin"] in done:
            continue
        job = {k: int(float(j[k])) for k in ("alert_block", "hit_block", "end_block")}
        try:
            xfer = transfers(url, j["coin"], job["alert_block"] - 200, job["end_block"])
            logs = []
            for tx in chosen_txs(xfer, job):
                rec = rpc(url, "eth_getTransactionReceipt", [tx]) or {}
                for e in rec.get("logs", []):
                    if e["address"].lower() not in FOMO:
                        logs.append([j["coin"], int(e["blockNumber"], 16), tx, int(e["logIndex"], 16),
                                     e["address"].lower(), ",".join(e["topics"]), e["data"]])
        except RuntimeError as exc:
            print(f"{j['coin']}: hata {exc}", flush=True)
            continue
        with open(out / "coin_xfer.jsonl", "a") as f:
            f.writelines(json.dumps(x) + "\n" for x in xfer)
        with open(out / "venue_logs.jsonl", "a") as f:
            f.writelines(json.dumps(x) + "\n" for x in logs)
        with open(out / "done.txt", "a") as f:
            f.write(j["coin"] + "\n")
        print(f"{n + 1}/{len(jobs)} {j['coin'][:10]}: {len(xfer)} transfer, {len(logs)} havuz logu · "
              f"{time.time() - t0:.0f} sn", flush=True)
    done = set((out / "done.txt").read_text().split()) if (out / "done.txt").exists() else set()
    print(f"bitti: {len(done)}/{len(jobs)} coin", flush=True)
    if "--no-push" in sys.argv or not done:
        return
    if len(done) < len(jobs):  # pushed anyway (a rerun retries the failed coins and pushes again)
        print(f"{len(jobs) - len(done)} coin alınamadı; alınanlar gönderiliyor", flush=True)
    from dotenv import load_dotenv
    from rhscanner import solana_export
    load_dotenv(ROOT / ".env")
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "arastirma" / "bnb-geri"
        dest.mkdir(parents=True)
        for name in ("coin_xfer", "venue_logs"):  # parts well under GitHub's 100 MB file limit
            write_parts(out / f"{name}.jsonl", dest, name)
        (dest / "jobs.csv").write_text(jobs_path.read_text())
        solana_export.push(Path(tmp), f"arastirma/bnb-geri: {len(done)} BNB seçiminin havuz verisi",
                           os.environ["VERI_GITHUB_TOKEN"].strip())
    print("veri dalına gönderildi: arastirma/bnb-geri/", flush=True)


if __name__ == "__main__":
    main()
