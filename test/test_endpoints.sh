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

# ============================================
# Polydispersity Tools Tests
# ============================================

# Test get-polydispersity-options
echo "9. get-polydispersity-options"
mcp_call 10 "tools/call" '{"name":"get-polydispersity-options","arguments":{}}' | jq .
echo

# Test get-polydisperse-parameters for cylinder model
echo "10. get-polydisperse-parameters (cylinder)"
mcp_call 11 "tools/call" '{"name":"get-polydisperse-parameters","arguments":{"model_name":"cylinder"}}' | jq .
echo

# Test get-polydisperse-parameters for sphere model
echo "11. get-polydisperse-parameters (sphere)"
mcp_call 12 "tools/call" '{"name":"get-polydisperse-parameters","arguments":{"model_name":"sphere"}}' | jq .
echo

# Test run-analysis with polydispersity enabled
echo "12. run-analysis with polydispersity (cylinder, 10% gaussian PD on radius)"
if [ -n "$CSV_FILE" ]; then
  echo "   Using file: $CSV_FILE"
  mcp_call 13 "tools/call" "{
    \"name\":\"run-analysis\",
    \"arguments\":{
      \"name\":\"fitting-with-custom-model\",
      \"parameters\":{
        \"input_csv\":\"$CSV_FILE\",
        \"model\":\"cylinder\",
        \"engine\":\"bumps\",
        \"method\":\"amoeba\",
        \"param_overrides\":$CYLINDER_PARAMS,
        \"polydispersity\":{
          \"radius\":{
            \"pd_width\":0.1,
            \"pd_type\":\"gaussian\",
            \"pd_n\":10,
            \"vary\":false
          }
        }
      }
    }
  }" | jq .
else
  echo "   SKIPPED - no CSV files found in uploads"
fi
echo

# Test run-analysis with polydispersity on multiple parameters
# echo "13. run-analysis with multi-param polydispersity (cylinder, PD on radius + length)"
# if [ -n "$CSV_FILE" ]; then
#   echo "   Using file: $CSV_FILE"
#   mcp_call 14 "tools/call" "{
#     \"name\":\"run-analysis\",
#     \"arguments\":{
#       \"name\":\"fitting-with-custom-model\",
#       \"parameters\":{
#         \"input_csv\":\"$CSV_FILE\",
#         \"model\":\"cylinder\",
#         \"engine\":\"bumps\",
#         \"method\":\"amoeba\",
#         \"param_overrides\":$CYLINDER_PARAMS,
#         \"polydispersity\":{
#           \"radius\":{
#             \"pd_width\":0.1,
#             \"pd_type\":\"lognormal\",
#             \"pd_n\":10,
#             \"vary\":false
#           },
#           \"length\":{
#             \"pd_width\":0.15,
#             \"pd_type\":\"gaussian\",
#             \"pd_n\":10,
#             \"vary\":false
#           }
#         }
#       }
#     }
#   }" | jq .
# else
#   echo "   SKIPPED - no CSV files found in uploads"
# fi

# ============================================
# Structure Factor Tools Tests
# ============================================

# Test list-structure-factors
echo "13. list-structure-factors"
mcp_call 14 "tools/call" '{"name":"list-structure-factors","arguments":{}}' | jq .
echo

# Test get-structure-factor-parameters (sphere@hardsphere)
echo "14. get-structure-factor-parameters (sphere@hardsphere)"
mcp_call 15 "tools/call" '{"name":"get-structure-factor-parameters","arguments":{"form_factor":"sphere","structure_factor":"hardsphere"}}' | jq .
echo

# Test get-structure-factor-parameters (sphere@hayter_msa)
echo "15. get-structure-factor-parameters (sphere@hayter_msa)"
mcp_call 16 "tools/call" '{"name":"get-structure-factor-parameters","arguments":{"form_factor":"sphere","structure_factor":"hayter_msa"}}' | jq .
echo

# Get sphere model parameters for structure factor tests
echo "16. Fetching sphere model parameters for structure factor tests"
SPHERE_PARAMS_RESPONSE=$(mcp_call 17 "tools/call" '{"name":"get-model-parameters","arguments":{"model_name":"sphere"}}')
SPHERE_PARAMS=$(echo "$SPHERE_PARAMS_RESPONSE" | jq -c '.result.content[0].text | fromjson // {}')
SPHERE_PARAMS=$(echo "$SPHERE_PARAMS" | jq -c '
  walk(if type == "object" then del(.description) else . end) |
  .radius.vary = true |
  .scale.vary = true |
  .background.vary = true
')
echo "   Sphere parameters (filtered + vary=true): $SPHERE_PARAMS"
echo

# Test run-analysis with hardsphere structure factor
echo "17. run-analysis with structure factor (sphere@hardsphere)"
if [ -n "$CSV_FILE" ]; then
  echo "   Using file: $CSV_FILE"
  mcp_call 18 "tools/call" "{
    \"name\":\"run-analysis\",
    \"arguments\":{
      \"name\":\"fitting-with-custom-model\",
      \"parameters\":{
        \"input_csv\":\"$CSV_FILE\",
        \"model\":\"sphere\",
        \"engine\":\"bumps\",
        \"method\":\"amoeba\",
        \"param_overrides\":$SPHERE_PARAMS,
        \"structure_factor\":\"hardsphere\",
        \"structure_factor_params\":{
          \"volfraction\":{\"value\":0.2,\"min\":0.0,\"max\":0.6,\"vary\":true},
          \"radius_effective\":{\"value\":50,\"min\":10,\"max\":100,\"vary\":true}
        }
      }
    }
  }" | jq .
else
  echo "   SKIPPED - no CSV files found in uploads"
fi
echo

# Test run-analysis with structure factor and link_radius mode
echo "18. run-analysis with structure factor + link_radius mode (sphere@hardsphere)"
if [ -n "$CSV_FILE" ]; then
  echo "   Using file: $CSV_FILE"
  mcp_call 19 "tools/call" "{
    \"name\":\"run-analysis\",
    \"arguments\":{
      \"name\":\"fitting-with-custom-model\",
      \"parameters\":{
        \"input_csv\":\"$CSV_FILE\",
        \"model\":\"sphere\",
        \"engine\":\"bumps\",
        \"method\":\"amoeba\",
        \"param_overrides\":$SPHERE_PARAMS,
        \"structure_factor\":\"hardsphere\",
        \"structure_factor_params\":{
          \"volfraction\":{\"value\":0.2,\"min\":0.0,\"max\":0.6,\"vary\":true}
        },
        \"radius_effective_mode\":\"link_radius\"
      }
    }
  }" | jq .
else
  echo "   SKIPPED - no CSV files found in uploads"
fi
echo

# Test run-analysis with hayter_msa structure factor (charged spheres)
echo "19. run-analysis with charged sphere structure factor (sphere@hayter_msa)"
if [ -n "$CSV_FILE" ]; then
  echo "   Using file: $CSV_FILE"
  mcp_call 20 "tools/call" "{
    \"name\":\"run-analysis\",
    \"arguments\":{
      \"name\":\"fitting-with-custom-model\",
      \"parameters\":{
        \"input_csv\":\"$CSV_FILE\",
        \"model\":\"sphere\",
        \"engine\":\"bumps\",
        \"method\":\"amoeba\",
        \"param_overrides\":$SPHERE_PARAMS,
        \"structure_factor\":\"hayter_msa\",
        \"structure_factor_params\":{
          \"volfraction\":{\"value\":0.2,\"min\":0.0,\"max\":0.6,\"vary\":true},
          \"radius_effective\":{\"value\":50,\"min\":10,\"max\":100,\"vary\":true},
          \"charge\":{\"value\":10,\"min\":0,\"max\":100,\"vary\":true}
        }
      }
    }
  }" | jq .
else
  echo "   SKIPPED - no CSV files found in uploads"
fi
echo

echo "=== Done ==="
