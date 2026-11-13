#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  echo "Najprej pripravite virtualno okolje z ./scripts/setup.sh" >&2
  exit 1
fi
# Refuse production endpoints before starting a consumer or a collector.
.venv/bin/python - <<'PY'
import os, sys
from urllib.parse import urlsplit
sys.path.insert(0, 'backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'radar.settings')
from django.conf import settings
config = settings.DATABASES['default']
storage = urlsplit(settings.PIPELINE_S3_ENDPOINT)
if not (config['ENGINE'].endswith('postgresql') and config['HOST'] == '127.0.0.1'
        and str(config['PORT']) == '5433' and config['NAME'] == 'razpizi_local'
        and settings.PIPELINE_REMOTE and storage.scheme == 'http'
        and storage.hostname == '127.0.0.1' and storage.port == 9003):
    raise SystemExit('Ta skripta zahteva lokalno bazo razpizi_local:5433 in shrambo 127.0.0.1:9003 iz .env.local.example.')
PY
.venv/bin/python backend/manage.py check_pipeline_connection
.venv/bin/python backend/manage.py pipeline_worker &
LOCAL_WORKER_PID=$!
trap 'kill "$LOCAL_WORKER_PID" 2>/dev/null || true' EXIT INT TERM
.venv/bin/python backend/manage.py enqueue_pipeline --watch &
LOCAL_SCHEDULER_PID=$!
trap 'kill "$LOCAL_WORKER_PID" "$LOCAL_SCHEDULER_PID" 2>/dev/null || true' EXIT INT TERM
# Exit together if either process stops, rather than leaving half a pipeline running.
while kill -0 "$LOCAL_WORKER_PID" 2>/dev/null && kill -0 "$LOCAL_SCHEDULER_PID" 2>/dev/null; do
  sleep 2
done
exit 1
