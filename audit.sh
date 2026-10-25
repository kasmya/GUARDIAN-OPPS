#!/bin/bash
# GuardianOps end-to-end audit.
#
# Probes the running stack over HTTP and prints PASS / FAIL for each check
# together with the value actually observed. Exit code = number of failures.
#
#   bash audit.sh                      # against the default local ports
#   GUARDIAN_URL=... FRAUD_URL=... CHAOS_URL=... FRONTEND_URL=... bash audit.sh
#
# Intentionally NOT covered: POST /crash (it would terminate fraud-api; it is
# exercised by the scripted scenario in report/build/capture_screenshots.py).

G=${GUARDIAN_URL:-http://127.0.0.1:8002}
F=${FRAUD_URL:-http://127.0.0.1:8001}
C=${CHAOS_URL:-http://127.0.0.1:8003}
FE=${FRONTEND_URL:-http://127.0.0.1:8080}
PY=${PYTHON:-python}
TMP=$(mktemp)

pass=0
fail=0

# check NAME URL EXPR [METHOD] [EXPECTED_STATUS(es), e.g. 200 or "200|404"] [JSON_BODY]
check() {
  local name="$1" url="$2" expr="$3" method="${4:-GET}" expect="${5:-200}" body="${6:-}"
  local code
  if [ "$method" = "POST" ]; then
    if [ -n "$body" ]; then
      code=$(curl -s -m 15 -X POST -H 'Content-Type: application/json' -d "$body" -o "$TMP" -w '%{http_code}' "$url")
    else
      code=$(curl -s -m 15 -X POST -o "$TMP" -w '%{http_code}' "$url")
    fi
  else
    code=$(curl -s -m 15 -o "$TMP" -w '%{http_code}' "$url")
  fi
  if [[ "|$expect|" != *"|$code|"* ]]; then
    printf "  FAIL  %-44s  http=%s (expected %s)\n" "$name" "$code" "$expect"
    fail=$((fail + 1)); return 1
  fi
  local v=""
  if [ -n "$expr" ]; then
    v=$($PY -c "import sys,json; d=json.load(open(sys.argv[1])); print($expr)" "$TMP" 2>&1 | head -1)
    if [[ "$v" == *Traceback* || "$v" == *Error* || "$v" == "ASSERT_FAIL"* ]]; then
      printf "  FAIL  %-44s  http=%s  %s\n" "$name" "$code" "$v"
      fail=$((fail + 1)); return 1
    fi
  fi
  printf "  PASS  %-44s  [%s] %s\n" "$name" "$code" "$v"
  pass=$((pass + 1))
}

# jget URL EXPR  -> prints the python expression value of a GET (used between checks)
jget() { curl -s -m 15 "$1" | $PY -c "import sys,json; d=json.load(sys.stdin); print($2)"; }

echo "=========================================================="
echo "  GuardianOps end-to-end audit   $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================================="
echo
echo "-- Service liveness --"
check "fraud-api  GET /health"       "$F/health"  "d['status']+' mode='+d['mode']"
check "guardian   GET /health"       "$G/health"  "d['status']"
check "chaos      GET /health"       "$C/health"  "d['status']"
echo
echo "-- Guardian: read endpoints --"
check "GET /status"                  "$G/status"           "'fraud_up=%s conf=%s active=%s' % (d['fraud_api_up'], d['confidence'], d.get('active_incident_type'))"
check "GET /live-metrics"            "$G/live-metrics"     "'uptime=%s%% p50=%sms' % (d['uptime_pct'], d.get('latency_ms_p50'))"
check "GET /baseline"                "$G/baseline"         "'size=%d mean=%.3f std=%.3f' % (d['size'], d['mean'], d['std'])"
check "GET /score-history"           "$G/score-history"    "'verdict=%s live=%d' % (d['current_verdict'], len(d['live']))"
check "GET /session-stats"           "$G/session-stats"    "'incidents=%d crashes=%d silent=%d' % (d['total_incidents'], d['crashes'], d['silent_failures'])"
check "GET /incidents"               "$G/incidents"        "'%d incident rows' % len(d['incidents'])"
check "GET /pending-approvals"       "$G/pending-approvals" "'%d pending' % len(d['pending'])"
check "GET /reports"                 "$G/reports"          "'%d report files' % len(d['reports'])"
check "GET /report/latest"           "$G/report/latest"    "('incident %s, %d bytes' % (d['incident_id'], len(d['markdown']))) if 'markdown' in d else 'none yet (404)'" GET "200|404"
check "GET /config"                  "$G/config"           "'alert=%s poll=%ss check=%ss window=%s' % (d['mutable']['psi_alert'], d['mutable']['poll_interval_s'], d['mutable']['drift_check_interval_s'], d['fixed']['window_size'])"
check "GET /metrics (prometheus)"    "$G/metrics"          ""
echo
echo "-- Guardian: write endpoints and negative cases --"
check "POST /check-now"              "$G/check-now"        "'verdict=%s psi=%s' % (d.get('verdict'), d.get('psi'))" POST
ORIG=$(jget "$G/config" "d['mutable']['psi_alert']")
check "POST /config psi_alert=0.25 is applied" "$G/config"  "d['mutable']['psi_alert'] if d['mutable']['psi_alert']==0.25 else 'ASSERT_FAIL got %s' % d['mutable']['psi_alert']" POST 200 '{"psi_alert":0.25}'
check "POST /config psi_alert=9 is clamped"    "$G/config"  "d['mutable']['psi_alert'] if d['mutable']['psi_alert']==1.0 else 'ASSERT_FAIL got %s' % d['mutable']['psi_alert']" POST 200 '{"psi_alert":9}'
check "POST /config restores original value"   "$G/config"  "d['mutable']['psi_alert'] if d['mutable']['psi_alert']==$ORIG else 'ASSERT_FAIL got %s' % d['mutable']['psi_alert']" POST 200 "{\"psi_alert\":$ORIG}"
check "POST /approve/999999 is refused (400)"  "$G/approve/999999" "d.get('detail')" POST 400
check "GET /reports/<traversal> is refused"    "$G/reports/..%2F..%2Fetc%2Fpasswd" "d.get('detail')" GET 404
FIRST=$(jget "$G/reports" "(d['reports'] or [''])[0]")
if [ -n "$FIRST" ]; then
  check "GET /reports/{name}"        "$G/reports/$FIRST"   "'%d bytes' % len(d['markdown'])"
else
  echo "  SKIP  GET /reports/{name}                            (no report files yet)"
fi
echo
echo "-- fraud-api: scoring and replay --"
check "fraud-api  GET /metrics"      "$F/metrics"          ""
check "fraud-api  POST /score"       "$F/score"            "'score=%.4f label=%s' % (d['score'], d['label'])" POST
check "POST /score high-risk -> fraud" "$F/score"          "'score=%.3f label=%s' % (d['score'], d['label']) if d['label']=='fraud' else 'ASSERT_FAIL label=%s' % d['label']" POST 200 '{"amount":9000,"merchant_category":"electronics","hour":3,"country_risk":0.9}'
check "POST /score invalid hour is refused (422)" "$F/score" "'rejected'" POST 422 '{"amount":10,"merchant_category":"atm","hour":99}'
check "fraud-api  GET /replay/info"  "$F/replay/info"      "'rows=%s' % d['rows']"
check "fraud-api  POST /replay?limit=500" "$F/replay?limit=500" "'n=%d TP=%d FP=%d TN=%d FN=%d precision=%s recall=%s f1=%s acc=%s' % (d['scored'], d['confusion_matrix']['true_positive'], d['confusion_matrix']['false_positive'], d['confusion_matrix']['true_negative'], d['confusion_matrix']['false_negative'], d['metrics']['precision'], d['metrics']['recall'], d['metrics']['f1'], d['metrics']['accuracy'])" POST
echo
echo "-- chaos-injector: failure modes really change fraud-api --"
check "chaos  POST /reset"           "$C/reset"            "'mode=%s' % d['mode']" POST
check "chaos  POST /slow?ms=300"     "$C/slow?ms=300"      "'scenario=%s' % d['scenario']" POST
check "  fraud-api now reports mode=slow"    "$F/health"   "d['mode'] if d['mode']=='slow' else 'ASSERT_FAIL mode=%s' % d['mode']"
check "chaos  POST /corrupt"         "$C/corrupt"          "'scenario=%s' % d['scenario']" POST
check "  fraud-api now reports mode=corrupt" "$F/health"   "d['mode'] if d['mode']=='corrupt' else 'ASSERT_FAIL mode=%s' % d['mode']"
check "chaos  POST /reset"           "$C/reset"            "'mode=%s' % d['mode']" POST
check "  fraud-api back to mode=normal"      "$F/health"   "d['mode'] if d['mode']=='normal' else 'ASSERT_FAIL mode=%s' % d['mode']"
echo
echo "-- Frontend --"
if curl -sf -m 10 -o /dev/null "$FE/index.html"; then
  echo "  PASS  dashboard GET /index.html"; pass=$((pass + 1))
else
  echo "  FAIL  dashboard GET /index.html"; fail=$((fail + 1))
fi
rm -f "$TMP"
echo
echo "=========================================================="
printf "  %d passed, %d failed.\n" "$pass" "$fail"
echo "=========================================================="
exit $fail
