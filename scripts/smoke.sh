#!/usr/bin/env bash
# SheetFlow smoke test: boots the real uvicorn server on a random port with a
# throwaway SQLite DB, hits the main endpoints with curl, greps for expected
# content, shuts the server down and prints PASS/FAIL. No Docker needed.
set -u
cd "$(dirname "$0")/.."

PORT=${SHEETFLOW_SMOKE_PORT:-$(( (RANDOM % 20000) + 20000 ))}
BASE="http://127.0.0.1:${PORT}"
TMPDB="$(mktemp "${TMPDIR:-/tmp}/sheetflow_smoke_XXXXXX.db")"
FAIL=0
SERVER_PID=""

cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
  rm -f "$TMPDB"
}
trap cleanup EXIT

echo "[smoke] starting uvicorn on :$PORT (temp DB)"
SHEETFLOW_DB="$TMPDB" python -m uvicorn app.main:app --port "$PORT" --log-level warning &
SERVER_PID=$!

# wait for readiness (max ~20s)
for _ in $(seq 1 40); do
  if curl -sf "$BASE/api/health" >/dev/null 2>&1; then break; fi
  sleep 0.5
done

check() { # <name> <url> <expected-substring> [extra curl args...]
  local name="$1" url="$2" expect="$3"; shift 3
  local body
  body=$(curl -sf "$@" "$url") || { echo "FAIL $name: request to $url failed"; FAIL=1; return; }
  if printf '%s' "$body" | grep -q "$expect"; then
    echo "PASS $name"
  else
    echo "FAIL $name: missing '$expect' in response"; FAIL=1
  fi
}

check "health"        "$BASE/api/health" '"ok"'
check "index html"    "$BASE/" 'og:title'
check "favicon"       "$BASE/static/favicon.svg" '<svg'
check "templates"     "$BASE/api/templates" 'Замовлення'

TOKEN=$(curl -s -X POST "$BASE/api/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' \
  | python -c 'import sys,json;print(json.load(sys.stdin).get("token",""))')
if [ -z "$TOKEN" ]; then
  echo "FAIL login: no token"; FAIL=1
else
  echo "PASS login"
  AUTH="Authorization: Bearer $TOKEN"
  check "me"          "$BASE/api/me" '"role"' -H "$AUTH"
  check "users"       "$BASE/api/users" 'admin' -H "$AUTH"
  # create a collection from a template, then read its rows and audit
  CURL_OUT=$(curl -s -X POST "$BASE/api/collections/from-template" -H "$AUTH" \
    -H 'Content-Type: application/json' -d '{"template":"orders"}')
  if printf '%s' "$CURL_OUT" | grep -q 'collection_id'; then
    echo "PASS from-template"
    CID=$(printf '%s' "$CURL_OUT" | python -c 'import sys,json;print(json.load(sys.stdin)["collection_id"])')
    check "rows"   "$BASE/api/collections/$CID/rows"   'item'
    check "audit"  "$BASE/api/collections/$CID/audit"  'collection.created' -H "$AUTH"
  else
    echo "FAIL from-template: $CURL_OUT"; FAIL=1
  fi
  # logout invalidates the token
  curl -s -X POST "$BASE/api/logout" -H "$AUTH" >/dev/null
  if curl -sf "$BASE/api/me" -H "$AUTH" >/dev/null 2>&1; then
    echo "FAIL logout: token still valid after logout"; FAIL=1
  else
    echo "PASS logout"
  fi
fi

if [ "$FAIL" -eq 0 ]; then
  echo "[smoke] ALL PASS"
else
  echo "[smoke] FAILURES DETECTED"
fi
exit $FAIL
