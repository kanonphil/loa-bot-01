#!/usr/bin/env bash
# 봇 서버(Oracle) 1회 설정. 여러 번 실행해도 결과가 같다(멱등).
#
#   실행:  ssh bot 'bash -s' < scripts/ops/setup-bot-server.sh
#   옵션(앞에 붙여서):
#     RESTRICT_8000=1          봇 API(8000)를 웹 서버 IP에서만 받도록 방화벽 변경
#                              (옛 데스크톱 관리 앱 bot-app은 더 이상 접속 못 함)
#     BACKUP_PULL_KEY="ssh-ed25519 AAAA..."
#                              웹 서버가 최신 백업을 가져갈 때 쓰는 공개키(setup-web-server.sh가 출력)
#   예:  ssh bot "RESTRICT_8000=1 BACKUP_PULL_KEY='ssh-ed25519 AAAA... loa-backup-pull' bash -s" < scripts/ops/setup-bot-server.sh
#
# 하는 일
#   1. DB 백업: ~/bin/loa-backup.sh 설치, 매일 04:40 KST 실행, 14개 보관, 무결성 확인
#   2. 디스코드 봇 토큰을 systemd 유닛 파일(누구나 읽기 가능)에서 .env(소유자만 읽기)로 이동 → 봇 재시작
#   3. (선택) 8000 포트를 웹 서버에서만
#   4. (선택) 웹 서버의 원격 백업용 키 등록 — 그 키로는 최신 백업 파일 읽기 말고 아무것도 못 함
set -euo pipefail

REPO="$HOME/loa-bot-01"
WEB_IP="${WEB_IP:-}"  # 웹 서버 공인 IP — 공개 리포라 적어 두지 않고 RESTRICT_8000=1일 때 환경변수로 받는다
UNIT=/etc/systemd/system/loabot.service
RESTART=0

say() { printf '[bot-setup] %s\n' "$*"; }

# ── 1. 백업 ──────────────────────────────────────────────────────────────
install -d -m 700 "$HOME/bin" "$HOME/backups"
cat > "$HOME/bin/loa-backup.sh" <<'EOF'
#!/bin/sh
# 봇 DB 백업 — sqlite3 .backup(실행 중에도 일관된 사본) → 무결성 확인 → gzip → 최근 14개만 보관.
# 인자: 파일 이름 꼬리표(예: pre-deploy). 출력: 만든 파일 경로.
set -eu
d="$HOME/backups"; mkdir -p "$d"
f="$d/loa_bot-$(date -u +%Y%m%d-%H%M%S)${1:+-$1}.db"
sqlite3 "$HOME/loa-bot-01/loa_bot.db" ".backup '$f'"
if [ "$(sqlite3 "$f" 'pragma integrity_check')" != ok ]; then
  echo "무결성 확인 실패: $f" >&2; rm -f "$f"; exit 1
fi
gzip -f "$f"
ls -1t "$d"/loa_bot-*.db.gz | tail -n +15 | xargs -r rm --
echo "$f.gz"
EOF
cat > "$HOME/bin/latest-backup.sh" <<'EOF'
#!/bin/sh
# 웹 서버의 원격 백업 키가 강제로 실행하는 명령 — 최신 백업 파일 내용을 내보내기만 한다.
f=$(ls -1t "$HOME"/backups/loa_bot-*.db.gz 2>/dev/null | head -1)
[ -n "$f" ] && exec cat "$f"
exit 1
EOF
chmod 700 "$HOME/bin/loa-backup.sh" "$HOME/bin/latest-backup.sh"
say "첫 백업: $("$HOME/bin/loa-backup.sh" setup)"
# 서버 시간대는 UTC — 19:40 UTC = 04:40 KST(04:00 원정대 동기화 직후)
( crontab -l 2>/dev/null | grep -v 'loa-backup.sh' || true
  echo '40 19 * * * $HOME/bin/loa-backup.sh >> $HOME/backups/backup.log 2>&1' ) | crontab -
say "백업 cron 등록 (매일 04:40 KST)"

# ── 2. 봇 토큰을 .env로 ──────────────────────────────────────────────────
touch "$REPO/.env"
if sudo grep -q '^Environment="DISCORD_TOKEN=' "$UNIT"; then
  tok=$(sudo sed -n 's/^Environment="DISCORD_TOKEN=\(.*\)"$/\1/p' "$UNIT")
  if ! grep -q '^DISCORD_TOKEN=' "$REPO/.env"; then
    printf '\nDISCORD_TOKEN=%s\n' "$tok" >> "$REPO/.env"
  fi
  bak="$UNIT.bak-$(date +%Y%m%d%H%M%S)"
  sudo cp "$UNIT" "$bak" && sudo chmod 600 "$bak"
  sudo sed -i '/^Environment="DISCORD_TOKEN=/d' "$UNIT"
  sudo systemctl daemon-reload
  RESTART=1
  say "토큰을 유닛 파일에서 .env로 옮김 (유닛 백업: $bak, root만 읽기)"
else
  say "유닛 파일에 토큰 없음 — 건너뜀"
fi
chmod 600 "$REPO/.env"

# ── 3. (선택) 8000 포트를 웹 서버에서만 ───────────────────────────────────
if [ "${RESTRICT_8000:-0}" = 1 ]; then
  [ -n "$WEB_IP" ] || { say "RESTRICT_8000=1에는 WEB_IP=x.x.x.x 가 필요합니다"; exit 1; }
  if ! sudo iptables -C INPUT -s "$WEB_IP/32" -p tcp -m tcp --dport 8000 -j ACCEPT 2>/dev/null; then
    sudo iptables -I INPUT -s "$WEB_IP/32" -p tcp -m tcp --dport 8000 -j ACCEPT
  fi
  while sudo iptables -C INPUT -p tcp -m tcp --dport 8000 -j ACCEPT 2>/dev/null; do
    sudo iptables -D INPUT -p tcp -m tcp --dport 8000 -j ACCEPT
  done
  sudo netfilter-persistent save >/dev/null
  say "8000 포트: $WEB_IP 만 허용 (저장됨)"
fi

# ── 4. (선택) 웹 서버 원격 백업 키 ────────────────────────────────────────
if [ -n "${BACKUP_PULL_KEY:-}" ]; then
  line="command=\"$HOME/bin/latest-backup.sh\",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding $BACKUP_PULL_KEY"
  if ! grep -qF "$BACKUP_PULL_KEY" "$HOME/.ssh/authorized_keys"; then
    cp "$HOME/.ssh/authorized_keys" "$HOME/.ssh/authorized_keys.bak-$(date +%Y%m%d%H%M%S)"
    printf '%s\n' "$line" >> "$HOME/.ssh/authorized_keys"
    say "원격 백업 키 등록 (최신 백업 읽기 전용)"
  else
    say "원격 백업 키 이미 등록됨"
  fi
fi

# ── 재시작 + 확인 ─────────────────────────────────────────────────────────
if [ "$RESTART" = 1 ]; then
  sudo systemctl restart loabot
  for i in $(seq 1 15); do
    sleep 2
    code=$(curl -s -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:8000/api/status || true)
    [ "$code" = 401 ] && break
  done
  sleep 5
  if [ "$(systemctl is-active loabot)" = active ] && [ "${code:-}" = 401 ]; then
    say "봇 재시작 확인 (API 응답 정상)"
  else
    say "봇이 정상적으로 올라오지 않았습니다 — journalctl -u loabot -n 50 확인 필요"
    say "되돌리기: sudo cp $bak $UNIT && sudo systemctl daemon-reload && sudo systemctl restart loabot"
    exit 1
  fi
fi
say "완료"
