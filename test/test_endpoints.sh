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

# Test list-templates
echo "3. list-templates"
mcp_call 3 "tools/call" '{"name":"list-templates","arguments":{}}' | jq .
echo

# Test list-uploaded-files
echo "4. list-uploaded-files"
mcp_call 4 "tools/call" '{"name":"list-uploaded-files","arguments":{"extensions":["csv"]}}' | jq .
echo

# Test run-template using an uploaded file
echo "5. run-template (fitting-with-cylinder-model)"
# Get first CSV file from list-uploaded-files
CSV_FILE=$(mcp_call 5 "tools/call" '{"name":"list-uploaded-files","arguments":{"extensions":["csv"],"limit":1}}' | jq -r '.result.structuredContent.result[0].relative_path // empty')

if [ -n "$CSV_FILE" ]; then
  echo "   Using file: $CSV_FILE"
  mcp_call 6 "tools/call" "{
    \"name\":\"run-template\",
    \"arguments\":{
      \"name\":\"fitting-with-cylinder-model\",
      \"parameters\":{
        \"input_csv\":\"$CSV_FILE\",
        \"engine\":\"bumps\",
        \"method\":\"amoeba\"
      }
    }
  }" | jq .
else
  echo "   SKIPPED - no CSV files found in uploads"
fi

echo
echo "=== Done ==="
