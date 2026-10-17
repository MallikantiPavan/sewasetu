#!/bin/bash
# Quick token generator for testing MCP endpoints.
# Usage: ./get_tokens.sh <admin_password> [mobile]
# Example: ./get_tokens.sh dev-password 9876500001

set -e

BASE_URL="${BASE_URL:-http://localhost:8000}"
ADMIN_PASSWORD="${1:-dev-password}"
MOBILE="${2:-9876500001}"
REDIRECT_URI="http://localhost:8080/callback"

# PKCE S256 verifier and challenge (pre-computed for simplicity)
VERIFIER="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

echo "=== Registering OAuth Client ==="
REGISTER_RESPONSE=$(curl -s -X POST "${BASE_URL}/oauth/register" \
  -H "Content-Type: application/json" \
  -d '{"redirect_uris": ["'"${REDIRECT_URI}"'"], "client_name": "Test Client", "token_endpoint_auth_method": "none"}')
echo "$REGISTER_RESPONSE"
CLIENT_ID=$(echo "$REGISTER_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('client_id',''))")
echo ""
echo "Client ID: $CLIENT_ID"
echo ""

echo "=== Getting Citizen Token ==="

# Step 1: Authorize
AUTH_URL="${BASE_URL}/oauth/authorize?client_id=${CLIENT_ID}&redirect_uri=${REDIRECT_URI}&response_type=code&code_challenge=${CHALLENGE}&code_challenge_method=S256&scope=citizen&resource=http://localhost:8101"
echo "Visit this URL in a browser:"
echo "$AUTH_URL"
echo ""
echo "1. Enter mobile: $MOBILE"
echo "2. Get OTP from: ${BASE_URL}/__gateway/"
echo "3. Enter OTP and approve"
echo "4. Copy the 'code' from the redirect URL"
echo ""
read -p "Paste the code: " CITIZEN_CODE

# Step 2: Exchange
CITIZEN_TOKEN=$(curl -s -X POST "${BASE_URL}/oauth/token" \
  -d "grant_type=authorization_code" \
  -d "code=${CITIZEN_CODE}" \
  -d "code_verifier=${VERIFIER}" \
  -d "client_id=${CLIENT_ID}" \
  -d "redirect_uri=${REDIRECT_URI}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

echo ""
echo "Citizen token: ${CITIZEN_TOKEN:0:20}..."
echo ""

echo "=== Getting Officer Token ==="

# Step 1: Authorize
AUTH_URL="${BASE_URL}/oauth/authorize?client_id=${CLIENT_ID}&redirect_uri=${REDIRECT_URI}&response_type=code&code_challenge=${CHALLENGE}&code_challenge_method=S256&scope=officer&resource=http://localhost:8102"
echo "Visit this URL in a browser:"
echo "$AUTH_URL"
echo ""
echo "1. Enter username: admin"
echo "2. Enter password: $ADMIN_PASSWORD"
echo "3. Approve consent"
echo "4. Copy the 'code' from the redirect URL"
echo ""
read -p "Paste the code: " OFFICER_CODE

# Step 2: Exchange
OFFICER_TOKEN=$(curl -s -X POST "${BASE_URL}/oauth/token" \
  -d "grant_type=authorization_code" \
  -d "code=${OFFICER_CODE}" \
  -d "code_verifier=${VERIFIER}" \
  -d "client_id=${CLIENT_ID}" \
  -d "redirect_uri=${REDIRECT_URI}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

echo ""
echo "Officer token: ${OFFICER_TOKEN:0:20}..."
echo ""

echo "=== Running Eval Workflow ==="
export CITIZEN_MCP_TOKEN="$CITIZEN_TOKEN"
export OFFICER_MCP_TOKEN="$OFFICER_TOKEN"
EVAL_RUN_WORKFLOW=1 python evals/runner.py
