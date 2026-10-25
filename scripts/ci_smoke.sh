#!/bin/bash
# Boot the three services (plus the dashboard web server) as plain processes and
# run the endpoint audit and the end-to-end silent-failure scenario against them.
# Used by the `integration` job in .github/workflows/ci.yml; also runnable locally:
#
#   PYTHON=.venv/Scripts/python.exe bash scripts/ci_smoke.sh
#
# Requires ports 8001, 8002, 8003 and 8080 to be free.
set -uo pipefail
cd "$(dirname "$0")/.."

PY=${PYTHON:-python}
TMPD=$(mktemp -d)
command -v cygpath >/dev/null 2>&1 && TMPD=$(cygpath -m "$TMPD")     # Git Bash on Windows
mkdir -p "$TMPD/data" "$TMPD/reports" "$TMPD/mlflow"

export STATE_FILE="$TMPD/state.json"
export FRAUD_API_URL=http://127.0.0.1:8001
export DATA_DIR="$TMPD/data"
export REPORTS_DIR="$TMPD/reports"
export MLFLOW_TRACKING_URI="file:///${TMPD#/}/mlflow"

PIDS=()
cleanup() {
  for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done
  rm -rf "$TMPD" 2>/dev/null || true
}
trap cleanup EXIT

start() { "$@" >"$TMPD/svc.$RANDOM.log" 2>&1 & PIDS+=($!); }

start "$PY" -m uvicorn app.main:app --app-dir services/fraud-api       --port 8001 --host 127.0.0.1 --log-level warning
start "$PY" -m uvicorn app.main:app --app-dir services/guardian        --port 8002 --host 127.0.0.1 --log-level warning
start "$PY" -m uvicorn app.main:app --app-dir services/chaos-injector  --port 8003 --host 127.0.0.1 --log-level warning
start "$PY" -m http.server 8080 --directory frontend --bind 127.0.0.1

echo "waiting for the four services ..."
for i in $(seq 1 60); do
  if curl -sf -o /dev/null http://127.0.0.1:8001/health && curl -sf -o /dev/null http://127.0.0.1:8002/health \
     && curl -sf -o /dev/null http://127.0.0.1:8003/health && curl -sf -o /dev/null http://127.0.0.1:8080/index.html; then
    echo "all up after ${i}s"; break
  fi
  sleep 1
  if [ "$i" = 60 ]; then echo "services did not come up"; cat "$TMPD"/*.log 2>/dev/null | tail -40; exit 1; fi
done

echo "waiting for the Guardian baseline ..."
for i in $(seq 1 60); do
  size=$(curl -s http://127.0.0.1:8002/baseline | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('size',0))" 2>/dev/null || echo 0)
  [ "${size:-0}" -ge 200 ] && break
  sleep 1
done

echo; echo "=== endpoint audit ==="
PYTHON="$PY" bash audit.sh; AUDIT=$?

echo; echo "=== end-to-end silent-failure scenario ==="
"$PY" scripts/e2e_scenario.py; E2E=$?

echo; echo "audit exit=$AUDIT  e2e exit=$E2E"
[ "$AUDIT" -eq 0 ] && [ "$E2E" -eq 0 ]
