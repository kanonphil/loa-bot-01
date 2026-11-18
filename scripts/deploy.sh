#!/usr/bin/env bash
# 서버 쪽 배포 스크립트 — GitHub Actions(.github/workflows/deploy.yml)가 SSH로 부른다.
#
# 서버의 ~/.ssh/authorized_keys에 배포 전용 키가 "강제 명령"으로 묶여 있어서, 그 키로는
# 이 스크립트 말고 아무것도 실행할 수 없다(셸·포트포워딩 불가):
#
#   command="cd ~/loa-bot-01 && git fetch -q origin main && git show origin/main:scripts/deploy.sh | bash -s -- bot",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA... github-actions-deploy
#
# 항상 origin/main의 최신 스크립트가 실행되므로 서버에 따로 설치·갱신할 것이 없다.
#
#   $1                    역할: bot | web
#   SSH_ORIGINAL_COMMAND  배포할 커밋(40자리 SHA) 또는 "check"(아무것도 안 바꾸고 상태만 출력)
#
# 동작: main을 해당 커밋으로 fast-forward → 이 서버가 쓰는 경로가 바뀐 경우에만 재시작
# (requirements가 바뀌면 pip install 먼저) → 헬스체크 → 실패하면 이전 커밋으로 되돌리고 재시작.
set -euo pipefail

main() {
  local role="${1:-}" req="${SSH_ORIGINAL_COMMAND:-check}"
  local repo="$HOME/loa-bot-01" service venv reqfile health_url
  local -a paths ok_codes

  case "$role" in
    bot)
      service=loabot venv=venv reqfile=requirements.txt
      paths=(bot config.py main.py requirements.txt)
      # 봇 API는 전부 X-API-Key가 필요해서 키 없이 부르면 401 — HTTP 서버가 떴다는 신호로 충분하다.
      health_url=http://127.0.0.1:8000/api/status ok_codes=(200 401) ;;
    web)
      service=loa-webapp venv=webapp/venv reqfile=webapp/requirements.txt
      paths=(webapp ':!webapp/tests')
      health_url=http://127.0.0.1:8080/health ok_codes=(200) ;;
    *) echo "역할은 bot 또는 web이어야 합니다: '$role'" >&2; return 2 ;;
  esac

  cd "$repo"
  exec 9>"/tmp/loa-deploy-$role.lock"
  flock -w 300 9 || { echo "다른 배포가 5분 넘게 끝나지 않았습니다." >&2; return 1; }

  local old; old=$(git rev-parse HEAD)
  echo "[$role] 현재 $(git log -1 --format='%h %s' "$old")"

  if [[ "$req" == check ]]; then
    echo "[$role] origin/main $(git log -1 --format='%h %s' origin/main)"
    echo "[$role] 서비스 $service: $(systemctl is-active "$service" || true)"
    git status --short | sed "s/^/[$role] 미커밋 변경: /"
    return 0
  fi

  if [[ ! "$req" =~ ^[0-9a-f]{40}$ ]]; then
    echo "배포 대상은 40자리 커밋 SHA여야 합니다." >&2; return 2
  fi
  local target="$req"
  git cat-file -e "$target^{commit}" 2>/dev/null || { echo "커밋 $target 이 서버에 없습니다(fetch 실패?)." >&2; return 1; }
  git merge-base --is-ancestor "$target" origin/main || { echo "커밋 $target 은 origin/main에 없습니다." >&2; return 1; }

  if [[ "$old" == "$target" ]]; then
    echo "[$role] 이미 최신입니다."; return 0
  fi
  if git merge-base --is-ancestor "$target" "$old"; then
    echo "[$role] 서버가 이미 더 새로운 커밋입니다(예전 실행의 재시도). 건너뜁니다."; return 0
  fi

  local changed; changed=$(git diff --name-only "$old" "$target" -- "${paths[@]}")
  git merge --ff-only -q "$target"   # 서버에서 직접 고친 파일이 있거나 갈라졌으면 여기서 멈춘다
  echo "[$role] 코드 갱신 → $(git log -1 --format='%h %s')"

  if [[ -z "$changed" ]]; then
    echo "[$role] 이 서버가 쓰는 파일은 바뀌지 않았습니다. 재시작 생략."; return 0
  fi
  echo "$changed" | sed "s/^/[$role]   변경: /" | head -30

  # 봇은 재시작 때 DB 마이그레이션이 돌 수 있어서 재시작 직전에 DB를 백업한다
  # (scripts/ops/setup-bot-server.sh가 ~/bin/loa-backup.sh를 설치해 둔 경우).
  local backup=""
  if [[ "$role" == bot && -x "$HOME/bin/loa-backup.sh" ]]; then
    if backup=$("$HOME/bin/loa-backup.sh" pre-deploy); then
      echo "[$role] 배포 전 DB 백업: $backup"
    else
      echo "[$role] 경고: 배포 전 DB 백업 실패 — 배포는 계속합니다" >&2
    fi
  fi

  local deps_changed=0
  if grep -qx "$reqfile" <<<"$changed"; then
    deps_changed=1
    echo "[$role] $reqfile 변경 → pip install"
    "$venv/bin/pip" install -q --disable-pip-version-check -r "$reqfile"
  fi

  if restart_and_check; then
    echo "[$role] 배포 완료: $(git log -1 --format='%h %s')"; return 0
  fi

  echo "[$role] 헬스체크 실패 — 최근 로그:" >&2
  journalctl -u "$service" -n 40 --no-pager >&2 || true
  echo "[$role] $(git rev-parse --short "$old") 로 되돌립니다." >&2
  git reset -q --hard "$old"
  if (( deps_changed )); then
    "$venv/bin/pip" install -q --disable-pip-version-check -r "$reqfile" || true
  fi
  if restart_and_check; then
    echo "[$role] 이전 버전으로 복구했습니다. (DB 마이그레이션이 이미 적용됐다면 그건 되돌려지지 않습니다${backup:+ — 배포 직전 DB: $backup})" >&2
  else
    echo "[$role] 복구 후에도 서비스가 올라오지 않습니다. 직접 확인이 필요합니다." >&2
  fi
  return 1
}

# 재시작 후 HTTP가 응답하고, 그 뒤 8초 동안 프로세스가 죽지 않고(PID 유지) 살아 있어야 성공.
# Restart=always라 시작 직후 죽는 코드도 순간적으로는 active로 보이기 때문에 PID를 본다.
restart_and_check() {
  sudo systemctl restart "$service"
  local i code pid
  for i in $(seq 1 20); do
    sleep 2
    code=$(curl -s -o /dev/null -m 3 -w '%{http_code}' "$health_url" || true)
    if [[ " ${ok_codes[*]} " == *" $code "* ]]; then
      pid=$(systemctl show -p MainPID --value "$service")
      sleep 8
      if [[ "$(systemctl is-active "$service")" == active && "$(systemctl show -p MainPID --value "$service")" == "$pid" ]]; then
        return 0
      fi
      return 1
    fi
  done
  return 1
}

main "$@"
