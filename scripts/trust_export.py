"""Train the trust score (PROJE.md §4.1) and export it for the bot: rhscanner/trust_model.json.

  python scripts/trust_export.py <security.parquet from scripts/security_study.py>

Trap = rug or unsellable. Flags at the 3rd-buyer moment, the same ones live.trust_flags computes. Logistic regression,
checked on the days from 26 Sep on with a model trained on the days before (AUC), then refit on every day.
Score = 100 * (1 - p / 0.5), clipped. Owner (§0, 3 Oct): the shared launchpad owner LAUNCHPAD_OWNER (owner of ~1.5k
Fomo coins, Pons/Doppler-hooked, no trap among them) does not count as "has an owner"; other owners do (46 % traps).
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rhscanner.live import LAUNCHPAD_OWNERS  # noqa: E402

ZERO = "0x" + "0" * 40
CUT = pd.Timestamp("2026-09-26").value / 1e9
FLAGS = ["satici2", "proxy", "sahip", "mint", "pause", "trading", "dev5", "hook_yok", "hook_baska", "liq1k", "pons_or_hook"]


def flags(s: pd.DataFrame, split_owner: bool = True) -> pd.DataFrame:
    owner = s.owner.fillna("").str.lower()
    has_owner = (owner != "") & (owner != ZERO)
    if split_owner:
        has_owner &= ~owner.isin(LAUNCHPAD_OWNERS)
    risky = s.risky.fillna("")
    hook = s.hook.fillna("").str.lower()
    is_addr = hook.str.startswith("0x")
    named = s.hook_named.fillna(False).astype(bool)
    return pd.DataFrame({
        "satici2": s.fomo_sellers >= 2,
        "proxy": s.proxy == 1,
        "sahip": has_owner,
        "mint": risky.str.contains("mint"),
        "pause": risky.str.contains("pause"),
        "trading": risky.str.contains("trading"),
        "dev5": s.dev_pct.fillna(0) > 5,
        "hook_yok": hook == ZERO,
        "hook_baska": is_addr & (hook != ZERO) & ~named,
        "liq1k": s.depth_usd.notna() & (2 * s.depth_usd < 1000),
        "pons_or_hook": s.pons.astype(bool) | named,
    }).astype(int)


def main():
    s = pd.read_parquet(sys.argv[1])
    s = s[s.obs_h >= 24].reset_index(drop=True)
    y = s.trap.astype(int)
    train, test = s.t0 < CUT, s.t0 >= CUT
    for name, split in (("eski (her sahip)", False), ("yeni (ortak launchpad sahibi hariç)", True)):
        X = flags(s, split)
        m = LogisticRegression(max_iter=1000).fit(X[train], y[train])
        auc = roc_auc_score(y[test], m.predict_proba(X[test])[:, 1])
        print(f"{name}: test AUC {auc:.3f} ({int(test.sum())} coin, tuzak %{100 * y[test].mean():.1f})")
    X = flags(s, True)
    m = LogisticRegression(max_iter=1000).fit(X, y)
    p = m.predict_proba(X)[:, 1]
    score = np.clip(100 * (1 - p / 0.5), 0, 100)
    for lo, hi in ((0, 50), (50, 70), (70, 85), (85, 101)):
        g = (score >= lo) & (score < hi)
        print(f"puan {lo}-{min(hi, 100)}: {int(g.sum())} coin, tuzak %{100 * y[g].mean() if g.any() else 0:.1f}")
    out = {"intercept": float(m.intercept_[0]), "coef": dict(zip(FLAGS, map(float, m.coef_[0]))), "half": 0.5,
           "note": "trap = rug or unsellable (PROJE.md §4.1); score = 100*(1 - p/half) clipped; scripts/trust_export.py"}
    (ROOT / "rhscanner" / "trust_model.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print("yazıldı: trust_model.json", {k: round(v, 2) for k, v in out["coef"].items()})


if __name__ == "__main__":
    main()
