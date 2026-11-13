#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python backend/manage.py check
ACCOUNT_REQUIRE_LOGIN=0 .venv/bin/python backend/manage.py test tenders --verbosity 2
npm --prefix frontend run build
docker compose config --quiet
