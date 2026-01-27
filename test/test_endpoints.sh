#!/bin/bash
# Test script for sans-pilot MCP endpoints
# Usage: ./test_endpoints.sh [base_url]
# Requires: curl, jq

set -e

BASE_URL="${1:-http://localhost:8001}"
MCP_ENDPOINT="$BASE_URL/mcp"

echo "=== Testing sans-pilot at $BASE_URL ==="
echo

# Helper to extract JSON from SSE response
parse_sse() {
  grep -o 'data: .*' | sed 's/data: //'
}

# Initialize session - get session ID from response header
echo "0. Initialize session"
INIT_RESPONSE=$(curl -s -i -X POST "$MCP_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}')

SESSION_ID=$(echo "$INIT_RESPONSE" | grep -i "mcp-session-id:" | cut -d' ' -f2 | tr -d '\r')
echo "$INIT_RESPONSE" | parse_sse | jq .

if [ -z "$SESSION_ID" ]; then
  echo "Failed to get session ID"
  exit 1
fi
echo "Session ID: $SESSION_ID"
echo

# Helper function for MCP calls
mcp_call() {
  local id=$1
  local method=$2
  local params=$3
  curl -s -X POST "$MCP_ENDPOINT" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "Mcp-Session-Id: $SESSION_ID" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":$id,\"method\":\"$method\",\"params\":$params}" | parse_sse
}

# Test tools/list
echo "1. tools/list"
mcp_call 1 "tools/list" "{}" | jq .
echo

# Test describe-possibilities
echo "2. describe-possibilities"
mcp_call 2 "tools/call" '{"name":"describe-possibilities","arguments":{}}' | jq .
echo

# Test list-sans-models
echo "3. list-sans-models"
mcp_call 3 "tools/call" '{"name":"list-sans-models","arguments":{}}' | jq .
echo

# Test get-model-parameters
echo "4. get-model-parameters (cylinder)"
mcp_call 4 "tools/call" '{"name":"get-model-parameters","arguments":{"model_name":"cylinder"}}' | jq .
echo

# Test list-analyses
echo "5. list-analyses"
mcp_call 5 "tools/call" '{"name":"list-analyses","arguments":{}}' | jq .
echo

# Test list-uploaded-files
echo "6. list-uploaded-files"
mcp_call 6 "tools/call" '{"name":"list-uploaded-files","arguments":{"extensions":["csv"]}}' | jq .
echo

# Get first CSV file for run-template tests
CSV_FILE=$(mcp_call 7 "tools/call" '{"name":"list-uploaded-files","arguments":{"extensions":["csv"],"limit":1}}' | jq -r '.result.content[0].text | fromjson | .[0].relative_path // empty')

# Get cylinder model parameters for param_overrides
echo "7. Fetching cylinder model parameters for run-analysis"
PARAMS_RESPONSE=$(mcp_call 8 "tools/call" '{"name":"get-model-parameters","arguments":{"model_name":"cylinder"}}')
# Extract the text content and parse as JSON
CYLINDER_PARAMS=$(echo "$PARAMS_RESPONSE" | jq -c '.result.content[0].text | fromjson // {}')
# Set vary=true for key fitting parameters and remove 'description' field (not accepted by set_param)
CYLINDER_PARAMS=$(echo "$CYLINDER_PARAMS" | jq -c '
  walk(if type == "object" then del(.description) else . end) |
  .radius.vary = true |
  .length.vary = true |
  .scale.vary = true |
  .background.vary = true
')
echo "   Model parameters (filtered + vary=true): $CYLINDER_PARAMS"
echo

# Test run-analysis with fitting-with-custom-model using fetched parameters
echo "8. run-analysis (fitting-with-custom-model, cylinder)"
if [ -n "$CSV_FILE" ]; then
  echo "   Using file: $CSV_FILE"
  mcp_call 9 "tools/call" "{
    \"name\":\"run-analysis\",
    \"arguments\":{
      \"name\":\"fitting-with-custom-model\",
      \"parameters\":{
        \"input_csv\":\"$CSV_FILE\",
        \"model\":\"cylinder\",
        \"engine\":\"bumps\",
        \"method\":\"amoeba\",
        \"param_overrides\":$CYLINDER_PARAMS
      }
    }
  }" | jq .
else
  echo "   SKIPPED - no CSV files found in uploads"
fi

echo
echo "=== Done ==="
