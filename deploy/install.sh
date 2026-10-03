#!/usr/bin/env bash
# One-command setup on a fresh Ubuntu server (e.g. Oracle Cloud Always Free):
#
#   curl -fsSL https://raw.githubusercontent.com/Kathaarian666/Coin/refs/heads/claude/fomo-coin-scanner-app-mhz9rk/deploy/install.sh | bash
#
# Installs dependencies, clones the bot, asks for the Telegram token, starts the
# bot as a systemd service (auto-restart, starts on boot) and then asks for the
# chat ID the bot reports on /start. Safe to run again to update.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Kathaarian666/Coin.git}"
BRANCH="${BRANCH:-claude/fomo-coin-scanner-app-mhz9rk}"
APP_DIR="${APP_DIR:-$HOME/Coin}"
SERVICE=rhscanner

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ask() { local reply; read -r -p "$1" reply </dev/tty; printf '%s' "$reply"; }
set_env() {  # set_env KEY VALUE: replace or append KEY=VALUE in .env
    if grep -q "^$1=" "$APP_DIR/.env"; then
        sed -i "s|^$1=.*|$1=$2|" "$APP_DIR/.env"
    else
        echo "$1=$2" >>"$APP_DIR/.env"
    fi
}

# Everything runs inside main() so bash parses the whole file before the
# update step below rewrites it on disk.
main() {
say "Paketler kuruluyor (git, python)..."
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git python3-venv python3-pip >/dev/null

say "Kod indiriliyor..."
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch -q origin "$BRANCH"
    git -C "$APP_DIR" checkout -q "$BRANCH"
    git -C "$APP_DIR" reset -q --hard "origin/$BRANCH"
else
    git clone -q --single-branch -b "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
# bash is still running the copy it read before the update: start the freshly downloaded one instead
if [ -z "${RHS_UPDATED:-}" ]; then
    RHS_UPDATED=1 exec bash "$APP_DIR/deploy/install.sh" "$@"
fi

say "Python ortamı hazırlanıyor (1-3 dakika sürebilir)..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
fi
chmod 600 "$APP_DIR/.env"
# Older installs used 8 req/s, which trips the public RPC's burst limit.
sed -i 's/^RPC_MAX_RPS=8$/RPC_MAX_RPS=6/' "$APP_DIR/.env"

if ! grep -q '^TELEGRAM_BOT_TOKEN=.\+' "$APP_DIR/.env"; then
    say "Telegram bot token'ı gerekiyor (@BotFather'dan aldığınız, 123456:ABC... şeklinde)"
    token=""
    while ! [[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]{20,}$ ]]; do
        token="$(ask "Token'ı yapıştırıp Enter'a basın: ")"
        token="${token//[[:space:]]/}"
        [[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]{20,}$ ]] || echo "Bu bir bot token'ına benzemiyor, tekrar deneyin."
    done
    set_env TELEGRAM_BOT_TOKEN "$token"
fi

say "Bot servisi kuruluyor (7/24 çalışacak, sunucu yeniden başlarsa kendiliğinden açılacak)..."
sudo tee /etc/systemd/system/$SERVICE.service >/dev/null <<EOF
[Unit]
Description=Fomo Robinhood Chain token scanner Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m rhscanner
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable -q $SERVICE
sudo systemctl restart $SERVICE
sleep 5
if ! systemctl is-active -q $SERVICE; then
    echo "Bot başlatılamadı. Son loglar:"
    sudo journalctl -u $SERVICE -n 30 --no-pager
    exit 1
fi

say "Pump.fun veri toplayıcı kuruluyor (Fomo'nun Solana işlemleri -> $APP_DIR/solana.db)..."
sudo tee /etc/systemd/system/fomosol.service >/dev/null <<EOF
[Unit]
Description=Fomo Solana (pump.fun / PumpSwap) trade collector
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m rhscanner.solana $APP_DIR/solana.db
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable -q fomosol
sudo systemctl restart fomosol

say "BNB veri toplayıcı kuruluyor (Fomo'nun BNB işlemleri + flap.sh lansmanları -> $APP_DIR/bnb.db)..."
sudo tee /etc/systemd/system/fombnb.service >/dev/null <<EOF
[Unit]
Description=Fomo BNB Chain trade + flap.sh launch collector
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m rhscanner.bnb $APP_DIR/bnb.db
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable -q fombnb
sudo systemctl restart fombnb

# every night: the finished days of solana.db and bnb.db -> GitHub `veri` branch (needs VERI_GITHUB_TOKEN in .env)
sudo tee /etc/systemd/system/fomosol-export.service >/dev/null <<EOF
[Unit]
Description=Send the finished days of the pump.fun and BNB data to the GitHub veri branch
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$(id -un)
WorkingDirectory=$APP_DIR
ExecStart=-$APP_DIR/.venv/bin/python -m rhscanner.solana_export $APP_DIR/solana.db
ExecStart=$APP_DIR/.venv/bin/python -m rhscanner.solana_export $APP_DIR/bnb.db --chain bnb
EOF
sudo tee /etc/systemd/system/fomosol-export.timer >/dev/null <<EOF
[Unit]
Description=Nightly pump.fun data export

[Timer]
OnCalendar=*-*-* 00:20:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable -q --now fomosol-export.timer

if ! grep -q '^TELEGRAM_CHAT_IDS=.\+' "$APP_DIR/.env"; then
    say "Son adım: Telegram'da botunuza /start yazın. Bot size 'Sohbet ID'niz: ...' diye bir sayı söyleyecek."
    chat=""
    while ! [[ "$chat" =~ ^-?[0-9]+$ ]]; do
        chat="$(ask "O sayıyı buraya yazıp Enter'a basın: ")"
        chat="${chat//[[:space:]]/}"
    done
    set_env TELEGRAM_CHAT_IDS "$chat"
    sudo systemctl restart $SERVICE
fi

say "Kurulum tamam! 🎉 Telegram'da botunuza /start ve /trend yazarak deneyin."
echo "Faydalı komutlar:"
echo "  Logları izle:    journalctl -u $SERVICE -f"
echo "  Yeniden başlat:  sudo systemctl restart $SERVICE"
echo "  Güncelle:        bash $APP_DIR/deploy/install.sh"
}

main "$@"
