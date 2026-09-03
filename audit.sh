#!/bin/bash
# GuardianOps end-to-end audit.
# Probes every backend endpoint. Every line prints PASS or FAIL plus the
# actual observed value so you can spot-check without opening the dashboard.
#
# Usage:
#   bash audit.sh

G=http://127.0.0.1:8002
F=http://127.0.0.1:8001
C=http://127.0.0.1:8003

pass=0
fail=0

check() {
  local name="$1" url="$2" jq_expr="$3" method="${4:-GET}"
  local resp
  if [ "$method" = "POST" ]; then
    resp=$(curl -s -X POST -o /tmp/audit_resp.json -w '%{http_code}' "$url")
  else
    resp=$(curl -s -o /tmp/audit_resp.json -w '%{http_code}' "$url")
  fi
  if [ "$resp" != "200" ]; then
    printf "  FAIL  %-40s  http=%s\n" "$name" "$resp"
    fail=$((fail + 1))
    return 1
  fi
  if [ -n "$jq_expr" ]; then
    local v
    v=$(python -c "import sys,json; d=json.load(sys.stdin); print($jq_expr)" \
        < /tmp/audit_resp.json 2>&1 | head -1)
    printf "  PASS  %-40s  %s\n" "$name" "$v"
  else
    printf "  PASS  %-40s\n" "$name"
  fi
  pass=$((pass + 1))
}

echo "=========================================================="
echo "  GuardianOps end-to-end audit"
echo "=========================================================="
echo
echo "-- Service liveness --"
check "fraud-api /health"        "$F/health"        "d['status']+' mode='+d['mode']"
check "guardian /health"         "$G/health"        "d['status']"
check "chaos-injector /health"   "$C/health"        "d['status']"
echo
echo "-- Guardian read endpoints --"
check "GET /status"              "$G/status"        "'fraud_up=%s conf=%s active=%s' % (d['fraud_api_up'], d['confidence'], d.get('active_incident_type'))"
check "GET /live-metrics"        "$G/live-metrics"  "'uptime=%s%% lat=%sms' % (d['uptime_pct'], d.get('latency_ms_p50'))"
check "GET /baseline"            "$G/baseline"      "'size=%d mean=%.3f std=%.3f' % (d['size'], d['mean'], d['std'])"
check "GET /score-history"       "$G/score-history" "'baseline_mean=%.3f verdict=%s live=%d' % (d['baseline_mean'], d['current_verdict'], len(d['live']))"
check "GET /session-stats"       "$G/session-stats" "'total=%d crashes=%d silents=%d' % (d['total_incidents'], d['crashes'], d['silent_failures'])"
check "GET /incidents"           "$G/incidents"     "'%d incidents' % len(d['incidents'])"
check "GET /pending-approvals"   "$G/pending-approvals" "'%d pending' % len(d['pending'])"
check "GET /reports"             "$G/reports"       "'%d reports' % len(d['reports'])"
check "GET /metrics (guardian)"  "$G/metrics"       ""
check "GET /metrics (fraud-api)" "$F/metrics"       ""
echo
echo "-- Fraud-API scoring (real math) --"
check "POST /score (fraud-api)"  "$F/score"         "'score=%.4f label=%s' % (d['score'], d['label'])" POST
echo
echo "-- Guardian action endpoints --"
check "POST /check-now"          "$G/check-now"     "'psi=%.3f verdict=%s' % (d.get('psi', 0), d.get('verdict', '?'))" POST
echo
echo "-- Chaos endpoints (write side) --"
check "POST /chaos/reset"        "$C/reset"         "'mode=%s' % d['mode']" POST
check "POST /chaos/slow?ms=500"  "$C/slow?ms=500"   "'scenario=%s' % d['scenario']" POST
check "POST /chaos/reset"        "$C/reset"         "'mode=%s' % d['mode']" POST
check "POST /chaos/corrupt"      "$C/corrupt"       "'scenario=%s' % d['scenario']" POST
check "POST /chaos/reset"        "$C/reset"         "'mode=%s' % d['mode']" POST
echo
echo "-- Frontend --"
if curl -sf http://127.0.0.1:8080/index.html > /dev/null; then
  echo "  PASS  frontend /index.html"
  pass=$((pass + 1))
else
  echo "  FAIL  frontend /index.html"
  fail=$((fail + 1))
fi
echo
echo "=========================================================="
printf "  %d passed, %d failed.\n" "$pass" "$fail"
echo "=========================================================="

exit $fail
