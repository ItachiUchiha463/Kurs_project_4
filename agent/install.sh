#!/usr/bin/env bash
# Встановлення агента Vigil на Linux однією командою (ТЗ 5.1.1). Потрібні root і Python 3.11+.
#
#   curl -fsSL <адреса>/install.sh | sudo bash -s -- --server https://vigil.example.com --token vgl_... --host web-01
#
# Повторний запуск оновлює код і налаштування та перезапускає службу. Видалення: ... --uninstall
set -euo pipefail

TARBALL="${VIGIL_AGENT_TARBALL:-https://github.com/ItachiUchiha463/Kurs_project_4/archive/refs/heads/main.tar.gz}"
DIR="${VIGIL_AGENT_DIR:-/opt/vigil-agent}"
SERVER="" TOKEN="" HOST="" SRC_DIR="" INTERVAL=15
DOCKER=0 POSTGRES=0 SERVICE=1 UNINSTALL=0

die() { echo "Помилка: $*" >&2; exit 1; }
usage() {
  cat <<'EOF'
Використання: install.sh --server URL --token ТОКЕН --host НАЗВА [параметри]

  --server URL     адреса Vigil, наприклад https://vigil.example.com
  --token ТОКЕН    токен агента зі сторінки об'єкта (vgl_...)
  --host НАЗВА     назва сервера, рівно та, що в Vigil
  --interval СЕК   інтервал надсилання, не менше 15 (типово 15)
  --docker         моніторити Docker-контейнери (запустить docker-socket-proxy, лише читання)
  --postgres       встановити драйвер PostgreSQL (бази підключаються в agent.toml, див. docs/DEPLOY.md)
  --no-service     не створювати службу systemd
  --src-dir DIR    взяти код агента з локальної папки, а не з GitHub
  --uninstall      видалити агента
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --server) SERVER="${2:-}"; shift 2 ;;
    --token) TOKEN="${2:-}"; shift 2 ;;
    --host) HOST="${2:-}"; shift 2 ;;
    --interval) INTERVAL="${2:-}"; shift 2 ;;
    --src-dir) SRC_DIR="${2:-}"; shift 2 ;;
    --docker) DOCKER=1; shift ;;
    --postgres) POSTGRES=1; shift ;;
    --no-service) SERVICE=0; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "невідомий параметр $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "запустіть від root (додайте sudo перед bash)"

if [ "$UNINSTALL" -eq 1 ]; then
  systemctl disable --now vigil-agent 2>/dev/null || true
  rm -f /etc/systemd/system/vigil-agent.service && systemctl daemon-reload 2>/dev/null || true
  rm -rf "$DIR"
  id vigil-agent >/dev/null 2>&1 && userdel vigil-agent || true
  echo "Агента видалено."; exit 0
fi

# значення потрапляють у agent.toml: перевіряємо, щоб не зламати файл і не вставити зайве
[[ "$SERVER" =~ ^https?://[A-Za-z0-9.:_/-]+$ ]] || die "--server має вигляд https://адреса"
[[ "$TOKEN" =~ ^vgl_[A-Za-z0-9_-]+$ ]] || die "--token має вигляд vgl_..."
[[ -n "$HOST" && "$HOST" != *[\"\\\'$'\n']* ]] || die "--host порожній або містить лапки, \\ чи перенесення рядка"
[[ "$INTERVAL" =~ ^[0-9]+$ ]] && [ "$INTERVAL" -ge 15 ] || die "--interval: ціле число не менше 15"

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null && { PY="$c"; break; }
done
if [ -z "$PY" ] && command -v apt-get >/dev/null 2>&1; then
  echo "Встановлюю python3..."; apt-get update -qq && apt-get install -y -qq python3 python3-venv curl >/dev/null
  command -v python3 >/dev/null && python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' && PY=python3
fi
[ -n "$PY" ] || die "потрібен Python 3.11 або новіший (на Ubuntu це 24.04, на Debian – 12)"

echo "Завантажую код агента..."
mkdir -p "$DIR/app"
if [ -n "$SRC_DIR" ]; then
  cp -r "$SRC_DIR/agent.py" "$SRC_DIR/collectors" "$DIR/app/"
else
  command -v curl >/dev/null || die "потрібен curl"
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  curl -fsSL "$TARBALL" | tar -xz -C "$tmp"
  cp -r "$tmp"/*/agent/agent.py "$tmp"/*/agent/collectors "$DIR/app/"
fi
find "$DIR/app" -name __pycache__ -prune -exec rm -rf {} +

echo "Встановлюю залежності..."
if [ ! -x "$DIR/venv/bin/python" ]; then
  "$PY" -m venv "$DIR/venv" 2>/dev/null || { command -v apt-get >/dev/null && apt-get install -y -qq python3-venv >/dev/null && "$PY" -m venv "$DIR/venv"; } || die "не вдалося створити venv"
fi
EXTRA="psutil httpx"; [ "$POSTGRES" -eq 1 ] && EXTRA="$EXTRA psycopg[binary]"
"$DIR/venv/bin/pip" install -q --disable-pip-version-check $EXTRA

cat > "$DIR/app/agent.toml.new" <<EOF
server   = "$SERVER"
token    = "$TOKEN"
host     = "$HOST"
interval = $INTERVAL
docker   = $([ "$DOCKER" -eq 1 ] && echo true || echo false)
EOF
# власні налаштування (диски, бази) не затираємо: беремо їх зі старого файлу, якщо він є
if [ -f "$DIR/app/agent.toml" ]; then
  grep -vE '^(server|token|host|interval|docker)[[:space:]]*=' "$DIR/app/agent.toml" >> "$DIR/app/agent.toml.new" || true
fi
mv "$DIR/app/agent.toml.new" "$DIR/app/agent.toml"

id vigil-agent >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin vigil-agent
chown -R vigil-agent: "$DIR"; chmod 600 "$DIR/app/agent.toml"

if [ "$DOCKER" -eq 1 ]; then
  command -v docker >/dev/null || die "--docker: Docker не встановлено"
  if ! docker ps -a --format '{{.Names}}' | grep -qx vigil-docker-proxy; then
    docker run -d --name vigil-docker-proxy --restart unless-stopped -p 127.0.0.1:2375:2375 \
      -v /var/run/docker.sock:/var/run/docker.sock:ro -e CONTAINERS=1 -e EVENTS=1 -e INFO=1 -e POST=0 tecnativa/docker-socket-proxy >/dev/null
  fi
fi

if [ "$SERVICE" -eq 1 ]; then
  command -v systemctl >/dev/null || die "systemd не знайдено (запустіть із --no-service і керуйте агентом самі)"
  cat > /etc/systemd/system/vigil-agent.service <<EOF
[Unit]
Description=Vigil monitoring agent
After=network-online.target
Wants=network-online.target

[Service]
User=vigil-agent
WorkingDirectory=$DIR/app
ExecStart=$DIR/venv/bin/python agent.py --config agent.toml --log $DIR/agent.log
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload && systemctl enable vigil-agent >/dev/null 2>&1 && systemctl restart vigil-agent
  sleep 2
  systemctl is-active --quiet vigil-agent || { journalctl -u vigil-agent -n 20 --no-pager; die "служба не запустилась"; }
  echo "Готово. Агент працює; перші дані з'являться у Vigil приблизно за $INTERVAL с."
  echo "Журнал: journalctl -u vigil-agent -f   |   видалити: ... install.sh --uninstall"
else
  echo "Готово (без служби). Запуск: cd $DIR/app && $DIR/venv/bin/python agent.py --config agent.toml"
fi
