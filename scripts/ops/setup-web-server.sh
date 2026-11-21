#!/usr/bin/env bash
# 웹 서버(Lightsail) 1회 설정. 여러 번 실행해도 결과가 같다(멱등).
#
#   실행:  ssh web 'bash -s' < scripts/ops/setup-web-server.sh
#
# 하는 일
#   1. 폐기한 Gemini AI 설정(GEMINI_*, CHAT_*)을 webapp/.env에서 삭제(원본은 .env.bak-날짜로 보관), .env 소유자만 읽기
#   2. systemd 유닛에 --timeout-graceful-shutdown 5 추가 — 열린 실시간 연결(SSE) 때문에 재시작이 오래 걸리지 않게.
#      다음 재시작(배포)부터 적용.
#   3. 8080 포트를 Cloudflare IP와 이 서버 자신에서만 받도록 방화벽 설정 — 지금은 누구나 Cloudflare를 우회해
#      원본 IP:8080으로 직접 접속할 수 있다. Cloudflare 공식 IP 목록을 받아서 적용하고 재부팅 후에도 유지.
#   4. 봇 DB 원격 백업: 매일 05:10 KST에 봇 서버의 최신 백업을 이 서버로 가져와 14개 보관(다른 클라우드라 서버 하나가
#      통째로 사라져도 남는다). 알림 DB(webapp_notifications.db)도 같이 백업.
#      처음 실행하면 공개키를 출력한다 → setup-bot-server.sh 에 BACKUP_PULL_KEY 로 넘겨야 동작.
set -euo pipefail

REPO="$HOME/loa-bot-01"
ENVF="$REPO/webapp/.env"
UNIT=/etc/systemd/system/loa-webapp.service
BOT_IP="${BOT_IP:?봇 서버 공인 IP를 환경변수로 넘겨주세요: BOT_IP=x.x.x.x bash setup-web-server.sh}"  # 공개 리포라 주소를 적어 두지 않는다
say() { printf '[web-setup] %s\n' "$*"; }

# ── 1. .env 정리 ─────────────────────────────────────────────────────────
if grep -qE '^(GEMINI_API_KEY|GEMINI_MODEL|CHAT_DB_PATH|CHAT_RETENTION_DAYS)=' "$ENVF"; then
  bak="$ENVF.bak-$(date +%Y%m%d%H%M%S)"
  cp "$ENVF" "$bak" && chmod 600 "$bak"
  sed -i -E '/^(GEMINI_API_KEY|GEMINI_MODEL|CHAT_DB_PATH|CHAT_RETENTION_DAYS)=/d' "$ENVF"
  say "Gemini/채팅 설정 삭제 (원본: $bak)"
fi
chmod 600 "$ENVF"

# ── 2. 종료 대기 시간 ─────────────────────────────────────────────────────
if ! sudo grep -q -- '--timeout-graceful-shutdown' "$UNIT"; then
  sudo cp "$UNIT" "$UNIT.bak-$(date +%Y%m%d%H%M%S)"
  sudo sed -i -E 's#^(ExecStart=.*uvicorn webapp\.main:app .*--port 8080)$#\1 --timeout-graceful-shutdown 5#' "$UNIT"
  sudo systemctl daemon-reload
  say "uvicorn --timeout-graceful-shutdown 5 추가 (다음 재시작부터 적용)"
fi

# ── 3. 8080은 Cloudflare에서만 ───────────────────────────────────────────
if ! dpkg -s iptables-persistent >/dev/null 2>&1; then
  echo iptables-persistent iptables-persistent/autosave_v4 boolean true | sudo debconf-set-selections
  echo iptables-persistent iptables-persistent/autosave_v6 boolean true | sudo debconf-set-selections
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q iptables-persistent >/dev/null
fi
ranges=$(curl -fsS -m 15 https://www.cloudflare.com/ips-v4)
n=$(printf '%s\n' "$ranges" | grep -cE '^[0-9.]+/[0-9]+$' || true)
[ "$n" -ge 10 ] || { say "Cloudflare IP 목록을 받지 못함 — 방화벽 변경 중단"; exit 1; }
sudo iptables -N CF8080 2>/dev/null || sudo iptables -F CF8080
for r in $ranges; do sudo iptables -A CF8080 -s "$r" -j ACCEPT; done
sudo iptables -A CF8080 -s 127.0.0.0/8 -j ACCEPT
sudo iptables -A CF8080 -j DROP
sudo iptables -C INPUT -p tcp --dport 8080 -j CF8080 2>/dev/null || sudo iptables -I INPUT -p tcp --dport 8080 -j CF8080
sudo netfilter-persistent save >/dev/null
say "8080: Cloudflare $n개 대역 + localhost만 허용 (저장됨)"
say "되돌리기: sudo iptables -D INPUT -p tcp --dport 8080 -j CF8080 && sudo netfilter-persistent save"

# ── 4. 원격 백업 ─────────────────────────────────────────────────────────
install -d -m 700 "$HOME/bin" "$HOME/backups"
KEY="$HOME/.ssh/loa-backup-pull"
[ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N '' -C loa-backup-pull -f "$KEY"
cat > "$HOME/bin/pull-backups.sh" <<EOF
#!/bin/sh
# 봇 DB 최신 백업을 가져오고(강제 명령 키), 알림 DB도 백업한다. 14개 보관.
set -eu
d="\$HOME/backups"; ts=\$(date -u +%Y%m%d-%H%M%S)
tmp="\$d/.incoming.gz"
ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new ubuntu@$BOT_IP > "\$tmp"
gzip -t "\$tmp" && mv "\$tmp" "\$d/loa_bot-\$ts.db.gz"
python3 - "\$d/webapp_notifications-\$ts.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect("$REPO/webapp_notifications.db"); dst = sqlite3.connect(sys.argv[1])
src.backup(dst); dst.close(); src.close()
PY
gzip -f "\$d/webapp_notifications-\$ts.db"
ls -1t "\$d"/loa_bot-*.db.gz | tail -n +15 | xargs -r rm --
ls -1t "\$d"/webapp_notifications-*.db.gz | tail -n +15 | xargs -r rm --
EOF
chmod 700 "$HOME/bin/pull-backups.sh"
( crontab -l 2>/dev/null | grep -v 'pull-backups.sh' || true
  echo '10 20 * * * $HOME/bin/pull-backups.sh >> $HOME/backups/backup.log 2>&1' ) | crontab -
say "원격 백업 cron 등록 (매일 05:10 KST)"
say "봇 서버에 등록할 공개키(BACKUP_PULL_KEY):"
cat "$KEY.pub"
say "완료"
