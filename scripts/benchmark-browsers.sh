#!/usr/bin/env bash
# benchmark-browsers.sh — Compare Chrome CDP page load performance
# Runs against production frontend URLs from the test VM
# Usage: benchmark-browsers.sh [--host 192.168.8.234]

set -uo pipefail

TEST_HOST="${1:-192.168.8.234}"
CHROME_CDP="ws://${TEST_HOST}:9222"
PROD_HOST="192.168.8.244"

# Frontend URLs to test
declare -A URLS=(
    ["summitflow"]="http://${PROD_HOST}:3001"
    ["portfolio"]="http://${PROD_HOST}:3003"
    ["agent-hub"]="http://${PROD_HOST}:3002"
    ["monkey-fight"]="http://${PROD_HOST}:3000"
)

echo "Browser Benchmark — $(date)"
echo "Chrome CDP: ${CHROME_CDP}"
echo "Production: ${PROD_HOST}"
echo ""
printf "%-15s %-8s %-10s %-10s %-8s\n" "App" "Status" "Load(ms)" "DOM Nodes" "Errors"
printf "%-15s %-8s %-10s %-10s %-8s\n" "---" "---" "---" "---" "---"

for app in "${!URLS[@]}"; do
    url="${URLS[$app]}"

    # Use CDP to navigate and measure
    result=$(ssh kasadis@"${TEST_HOST}" "node -e '
const WebSocket = require(\"ws\");
const ws = new WebSocket(\"ws://127.0.0.1:9222/json/new\");
// This is a placeholder — full CDP automation requires puppeteer or similar
// For now, just verify connectivity
const http = require(\"http\");
const start = Date.now();
http.get(\"${url}\", (res) => {
    let data = \"\";
    res.on(\"data\", (chunk) => data += chunk);
    res.on(\"end\", () => {
        const elapsed = Date.now() - start;
        console.log(JSON.stringify({
            status: res.statusCode,
            loadMs: elapsed,
            bodySize: data.length,
            errors: 0
        }));
        process.exit(0);
    });
}).on(\"error\", (e) => {
    console.log(JSON.stringify({status: 0, loadMs: 0, bodySize: 0, errors: 1}));
    process.exit(1);
});
setTimeout(() => process.exit(1), 10000);
' 2>/dev/null")

    if [[ -n "$result" ]]; then
        status=$(echo "$result" | jq -r '.status')
        load_ms=$(echo "$result" | jq -r '.loadMs')
        body_size=$(echo "$result" | jq -r '.bodySize')
        errors=$(echo "$result" | jq -r '.errors')
        printf "%-15s %-8s %-10s %-10s %-8s\n" "$app" "$status" "${load_ms}ms" "${body_size}B" "$errors"
    else
        printf "%-15s %-8s %-10s %-10s %-8s\n" "$app" "FAIL" "-" "-" "1"
    fi
done

echo ""

# Container resource usage
echo "Container Resources:"
ssh kasadis@"${TEST_HOST}" "docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' 2>/dev/null" || echo "  (could not read docker stats)"
