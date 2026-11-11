#!/usr/bin/env bash
# Haftalık standart sınav (PROJE.md §4.16 / §4.16b, kullanıcı 11 Kasım: haftalık görev yeni ölçüte).
#
#   bash scripts/weekly_exam.sh [çalışma klasörü=/tmp/haftalik]
#
# Adımlar: araştırma venv'i → veri dalı (kısmi klon, /tmp/veri) → fomo.db (parquet arşivi + robinhood/ günleri, arz,
# Pons lansmanları) → veri sağlığı (son 14 günün günlük işlem sayısı) → winner_study → profit_study (5. alıcı, 2x
# modeli, walk-forward, en iyi %5) → scorecard --fetch (zincir olayları) → pool_depth (zincirden derinlik + ücret) →
# karne (başlık, kötümser, --dump). Çıktılar <çalışma>/ altında; kalıcı olanlar veri dalında arastirma/haftalik/
# (her hafta üzerine yazılır: seçimler, zincir olayları, derinlik) ve arastirma/haftalik/karne_<gün>.txt.
# Zincir RPC'si gerekir (rpc.mainnet.chain.robinhood.com / robinhood.drpc.org). veri dalına push en sonda, ayrı:
#   PUSH=1 bash scripts/weekly_exam.sh
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
W=${1:-/tmp/haftalik}
VERI=${VERI:-/tmp/veri}
PY=${PY:-$W/venv/bin/python}
TODAY=$(date -u +%F)
mkdir -p "$W" /tmp/claude-0/data   # profit_study.py yazdığı yer sabit
cd "$W"
log() { echo; echo "=== $(date -u +%H:%M:%S) $*"; }

if [ ! -x "$PY" ]; then
  log "venv"
  python3 -m venv "$W/venv"
  "$W/venv/bin/pip" install -q -r "$REPO/requirements-dev.txt" numpy pandas pyarrow scikit-learn
fi

if [ ! -d "$VERI/.git" ] && [ ! -f "$VERI/.git" ]; then
  log "veri dalı (kısmi klon)"
  git -C "$REPO" fetch --depth 1 --filter=blob:none origin veri
  git -C "$REPO" worktree add --no-checkout "$VERI" FETCH_HEAD
  git -C "$VERI" sparse-checkout set --no-cone '/arastirma/haftalik/' '/arastirma/2026-11-1*/' '/*.parquet' '/robinhood/'
  git -C "$VERI" checkout -q
fi

if [ ! -f fomo.db ]; then
  log "fomo.db"
  "$PY" "$REPO/scripts/data_import.py" "$VERI" fomo.db
  "$PY" "$REPO/scripts/solana_import.py" "$VERI" fomo.db --chain robinhood
  "$PY" "$REPO/scripts/fomo_supply.py" fomo.db
  "$PY" "$REPO/scripts/pons_launches.py" fomo.db
fi

log "veri sağlığı: günlük Fomo işlemi (son 14 gün; birden düşüş = bot kör, CLAUDE.md 'Zincir gerçekleri')"
"$PY" - <<'EOF'
import sqlite3, pandas as pd
db = sqlite3.connect("fomo.db")
d = pd.read_sql("SELECT date(ts, 'unixepoch') AS gun, COUNT(*) AS islem FROM trades GROUP BY gun ORDER BY gun", db)
med = d.islem.iloc[-30:-1].median()
for r in d.iloc[-14:].itertuples():
    print(f"  {r.gun}: {r.islem:>7}" + ("   <-- DÜŞÜK (30 gün medyanının %20'sinden az)" if r.islem < 0.2 * med else ""))
EOF

if [ ! -f winners.parquet ]; then
  log "winner_study (RAM ~7 GB)"
  "$PY" "$REPO/scripts/winner_study.py" fomo.db winners.parquet 2026-09-03 "$TODAY"
fi

if [ ! -f picks_top5.parquet ]; then
  log "profit_study (walk-forward, 10 Eylül'den)"
  "$PY" "$REPO/scripts/profit_study.py" fomo.db winners.parquet 2026-09-10 5 | tee profit_study.txt
  cp /tmp/claude-0/data/profit_k5_2x_0.05.parquet picks_top5.parquet
fi

log "zincir olayları (önceki haftaların dosyası veri dalından, eksikler indirilir)"
if [ ! -f events_top5.jsonl.gz ]; then
  for src in "$VERI/arastirma/haftalik/events_top5.jsonl.gz" "$VERI/arastirma/2026-11-10/events_top5.jsonl.gz"; do
    [ -f "$src" ] && { cp "$src" events_top5.jsonl.gz; break; }
  done
fi
"$PY" "$REPO/scripts/scorecard.py" fomo.db picks_top5.parquet events_top5.jsonl.gz --fetch > /dev/null

log "havuz derinliği (önceki haftaların ölçümü veri dalından, sadece yeni seçimler ölçülür)"
R=""
if [ -f pool_depth.parquet ]; then cp pool_depth.parquet pool_depth_onceki.parquet
elif [ -f "$VERI/arastirma/haftalik/pool_depth.parquet" ]; then
  cp "$VERI/arastirma/haftalik/pool_depth.parquet" pool_depth_onceki.parquet
fi
[ -f pool_depth_onceki.parquet ] && R="--reuse pool_depth_onceki.parquet"
"$PY" "$REPO/scripts/pool_depth.py" fomo.db picks_top5.parquet pool_depth.parquet $R | grep -v -E "^  [0-9]+/|^retry" || true

log "karne"
K="--depth pool_depth.parquet --fees pool_depth.parquet --v4-fee-floor 0.0148"
{
  echo "# Haftalık karne $TODAY (scripts/weekly_exam.sh; ölçülen derinlik + havuz ücreti, PROJE.md §4.16b)"
  echo "## ANA YÖNTEM (kullanıcı, 11 Kasım): sadece Pons dışı seçimler + yan kural = aşağıda İKİNCİ blok"
  "$PY" "$REPO/scripts/scorecard.py" fomo.db picks_top5.parquet events_top5.jsonl.gz $K --only-pons 0 --dump karne_dump.parquet
  echo; echo "## Ana yöntem kötümser: derinlik x0,5, alış 30 sn (ikinci blok)"
  "$PY" "$REPO/scripts/scorecard.py" fomo.db picks_top5.parquet events_top5.jsonl.gz $K --only-pons 0 --depth-scale 0.5 --delay 30
  echo; echo "## Karşılaştırma: eski yöntem (bütün seçimler, 5x'te hepsini sat = ilk blok)"
  "$PY" "$REPO/scripts/scorecard.py" fomo.db picks_top5.parquet events_top5.jsonl.gz $K
} | tee "karne_$TODAY.txt"

if [ "${PUSH:-0}" = 1 ]; then
  log "veri dalına kaydet (arastirma/haftalik/)"
  H="$VERI/arastirma/haftalik"
  mkdir -p "$H"
  cp picks_top5.parquet events_top5.jsonl.gz pool_depth.parquet "karne_$TODAY.txt" "$H/"
  git -C "$VERI" add -A arastirma/haftalik
  git -C "$VERI" commit -q -m "Haftalık karne $TODAY (scripts/weekly_exam.sh)"
  for i in 1 2 3 4; do git -C "$VERI" push origin HEAD:veri && break; sleep $((2 ** i)); done
fi
