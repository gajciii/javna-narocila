#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python || ! -d frontend/node_modules ]]; then
  echo "Najprej zaženite ./scripts/setup.sh" >&2
  exit 1
fi
RADAR_BACKEND_PORT="${RADAR_BACKEND_PORT:-8001}"
RADAR_FRONTEND_PORT="${RADAR_FRONTEND_PORT:-5174}"
.venv/bin/python - "$RADAR_BACKEND_PORT" "$RADAR_FRONTEND_PORT" <<'PY'
import socket, sys
for value in sys.argv[1:]:
    try:
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', int(value)))
    except (OSError, ValueError):
        raise SystemExit(f'Vrata {value} niso na voljo. Ustavite prejšnji zagon ali nastavite RADAR_BACKEND_PORT in RADAR_FRONTEND_PORT.')
PY
.venv/bin/python backend/manage.py migrate --noinput
.venv/bin/python backend/manage.py init_workspace
.venv/bin/python backend/manage.py runserver "127.0.0.1:$RADAR_BACKEND_PORT" --noreload &
RADAR_BACKEND_PID=$!
trap 'kill "$RADAR_BACKEND_PID" 2>/dev/null || true' EXIT INT TERM
API_PROXY_TARGET="http://127.0.0.1:$RADAR_BACKEND_PORT" npm --prefix frontend run dev -- --host 127.0.0.1 --port "$RADAR_FRONTEND_PORT" --strictPort
