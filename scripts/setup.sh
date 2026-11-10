#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3.12 python3.13 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Potrebujete Python 3.10 ali novejši (priporočeno 3.12)." >&2
  exit 1
fi
if [[ ! -d .venv ]]; then "$PYTHON_BIN" -m venv .venv; fi
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
.venv/bin/python backend/manage.py migrate --noinput
.venv/bin/python backend/manage.py seed_demo
echo "Okolje je pripravljeno. Zaženite ./scripts/dev.sh"
