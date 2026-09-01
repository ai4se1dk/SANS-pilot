#!/bin/bash
# Smoke-test the direct typed sans-pilot MCP contract.

set -euo pipefail

BASE_URL="${1:-http://localhost:8001}"
MCP_ENDPOINT="$BASE_URL/mcp"

parse_sse() {
  grep -o 'data: .*' | sed 's/data: //'
}

echo "0. Initialize MCP session"
INIT_RESPONSE=$(curl -s -i -X POST "$MCP_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"sans-pilot-smoke","version":"1.0"}}}')
SESSION_ID=$(echo "$INIT_RESPONSE" | grep -i "mcp-session-id:" | cut -d' ' -f2 | tr -d '\r')
test -n "$SESSION_ID"

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

echo "1. List tools"
TOOLS=$(mcp_call 1 "tools/list" '{}')
echo "$TOOLS" | jq .
for name in describe-sans-capabilities list-supported-sans-formats \
  list-uploaded-sans-files inspect-sans-data plot-sans-data process-sans-data \
  list-sans-models get-sans-model-parameters list-structure-factors \
  get-polydispersity-options fit-sans-model \
  scan-sans-dmax invert-sans-pr list-sans-examples inspect-sans-example \
  simulate-sans-data simulate-sans-pair; do
  echo "$TOOLS" | jq -e --arg name "$name" '.result.tools | any(.name == $name)' >/dev/null
done
for removed in list-analyses run-analysis get-model-parameters \
  get-structure-factor-parameters get-polydisperse-parameters; do
  echo "$TOOLS" | jq -e --arg name "$removed" '.result.tools | any(.name == $name) | not' >/dev/null
done

echo "2. Inspect deterministic simulated data"
mcp_call 2 "tools/call" '{"name":"inspect-sans-data","arguments":{"pipeline":{"primary":{"kind":"simulation","model":"sphere","parameters":{"radius":50},"points":30,"seed":42}}}}' | jq .

echo "3. Discover atomic model parameters"
mcp_call 3 "tools/call" '{"name":"get-sans-model-parameters","arguments":{"model":{"kind":"atomic","model":"cylinder"}}}' | jq .

echo "4. Discover interacting model parameters"
mcp_call 4 "tools/call" '{"name":"get-sans-model-parameters","arguments":{"model":{"kind":"atomic","model":"sphere","structure_factor":"hardsphere","radius_effective_mode":"link_radius"}}}' | jq .

echo "5. Discover composite model parameters"
mcp_call 5 "tools/call" '{"name":"get-sans-model-parameters","arguments":{"model":{"kind":"composite","operation":"+","components":[{"alias":"small","model":"sphere"},{"alias":"long","model":"cylinder"}],"shared_parameters":["sld","sld_solvent"]}}}' | jq .

echo "6. Run typed optimization fit"
FIT_RESPONSE=$(mcp_call 6 "tools/call" '{
  "name":"fit-sans-model",
  "arguments":{"request":{
    "pipeline":{"primary":{"kind":"simulation","model":"sphere","parameters":{"radius":50,"scale":0.1,"background":0.001},"points":40,"noise":0.03,"seed":42}},
    "model":{"kind":"atomic","model":"sphere"},
    "parameters":{
      "radius":{"value":40,"min":10,"max":100,"vary":true},
      "scale":{"value":0.08,"min":0.001,"max":1,"vary":true},
      "background":{"value":0.002,"min":0,"max":0.1,"vary":true}
    },
    "fit":{"mode":"optimization","engine":"bumps","method":"amoeba"},
    "artifacts":{"include_results_csv":true}
  }}
}')
echo "$FIT_RESPONSE" | jq .
echo "$FIT_RESPONSE" | jq -e '[.result.content[] | tostring] | any(test("fit_plot\\.png"))' >/dev/null
echo "$FIT_RESPONSE" | jq -e '[.result.content[] | tostring] | any(test("fit_results\\.csv"))' >/dev/null
echo "$FIT_RESPONSE" | jq -e '[.result.content[] | tostring] | any(test("sasview_parameter_values\\.txt"))' >/dev/null

echo "7. Discover and inspect curated examples"
mcp_call 7 "tools/call" '{"name":"list-sans-examples","arguments":{"tag":"biology"}}' | jq .
mcp_call 8 "tools/call" '{"name":"inspect-sans-example","arguments":{"name":"protein"}}' | jq .

echo "8. Generate reproducible simulated data"
mcp_call 9 "tools/call" '{"name":"simulate-sans-data","arguments":{"request":{"source":{"kind":"simulation","model":"sphere","parameters":{"radius":50},"points":25,"noise":0.02,"seed":42},"include_csv":false}}}' | jq .

echo "9. Scan Dmax and invert P(r)"
mcp_call 10 "tools/call" '{"name":"scan-sans-dmax","arguments":{"request":{"pipeline":{"primary":{"kind":"example","name":"protein"},"q_max":0.25},"d_max_guess":120,"d_min":100,"d_max":140,"points":5,"fit_background":false,"plot_quantity":"all"}}}' | jq .
mcp_call 11 "tools/call" '{"name":"invert-sans-pr","arguments":{"request":{"pipeline":{"primary":{"kind":"example","name":"protein"},"q_max":0.25},"d_max":120,"selection":{"mode":"automatic"},"fit_background":false,"plot_log_scale":false}}}' | jq .

echo "All typed MCP smoke tests passed."
