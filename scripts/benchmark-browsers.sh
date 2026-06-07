#!/usr/bin/env bash
# benchmark-browsers.sh — Compare Chrome vs Lightpanda CDP performance
# Runs Puppeteer-based tests on the Proxmox test VM against production frontends
#
# Usage:
#   benchmark-browsers.sh                     # Run full benchmark
#   benchmark-browsers.sh --iterations 5      # Custom iteration count
#   benchmark-browsers.sh --chrome-only       # Skip Lightpanda
#   benchmark-browsers.sh --lightpanda-only   # Skip Chrome

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load config
ENV_FILE="${PROJECT_DIR}/docker/compose/.env"
if [[ -f "$ENV_FILE" ]]; then
    eval "$(grep -E '^TEST_VM_HOST=' "$ENV_FILE" | sed 's/^/export /')"
fi

TEST_HOST="${TEST_VM_HOST:-}"
if [[ -z "$TEST_HOST" ]]; then
    echo "Set TEST_VM_HOST or pass --host." >&2
    exit 1
fi
ITERATIONS=3
RUN_CHROME=true
RUN_LIGHTPANDA=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --iterations)     ITERATIONS="$2"; shift 2 ;;
        --chrome-only)    RUN_LIGHTPANDA=false; shift ;;
        --lightpanda-only) RUN_CHROME=false; shift ;;
        --host)           TEST_HOST="$2"; shift 2 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

echo "Browser Benchmark — $(date)"
echo "Test VM: ${TEST_HOST} | Iterations: ${ITERATIONS}"
echo ""

# Run the Puppeteer benchmark on the test VM
BROWSERS=""
[[ "$RUN_CHROME" == true ]] && BROWSERS="${BROWSERS}chrome,"
[[ "$RUN_LIGHTPANDA" == true ]] && BROWSERS="${BROWSERS}lightpanda,"
BROWSERS="${BROWSERS%,}"

RAW=$(ssh "${TEST_VM_USER:-$USER}@${TEST_HOST}" "cd ~/benchmark && ITERATIONS=${ITERATIONS} BROWSERS=${BROWSERS} node run.js 2>&1")

# Parse and display results
echo "$RAW" | jq -r 'select(.event == "stats_before") | "Container Resources (before):\n" + (.stats | map("  \(.name): \(.cpu) CPU, \(.mem) RAM") | join("\n"))' 2>/dev/null || true
echo ""

# Results table
echo "Per-page results:"
printf "%-12s %-15s %-4s %-8s %-8s %-8s %-8s %-8s %-8s\n" "Browser" "Page" "Iter" "Load" "DOM-Q" "JS-Eval" "Extract" "Total" "Nodes"
printf "%-12s %-15s %-4s %-8s %-8s %-8s %-8s %-8s %-8s\n" "-------" "----" "----" "----" "-----" "-------" "-------" "-----" "-----"
echo "$RAW" | jq -r 'select(.event == "result" and .status == "ok") | [.browser, .page, .iteration, (.loadMs|tostring)+"ms", (.domQueryMs|tostring)+"ms", (.jsEvalMs|tostring)+"ms", (.extractMs|tostring)+"ms", (.totalMs|tostring)+"ms", .domNodes] | @tsv' 2>/dev/null \
    | while IFS=$'\t' read -r browser page iter load domq jseval extract total nodes; do
        printf "%-12s %-15s %-4s %-8s %-8s %-8s %-8s %-8s %-8s\n" "$browser" "$page" "$iter" "$load" "$domq" "$jseval" "$extract" "$total" "$nodes"
    done

# Errors
ERRORS=$(echo "$RAW" | jq -r 'select(.event == "result" and .status != "ok") | "\(.browser) \(.page) iter\(.iteration): \(.error // .status)"' 2>/dev/null || true)
if [[ -n "$ERRORS" ]]; then
    echo ""
    echo "Errors:"
    echo "$ERRORS" | sed 's/^/  /'
fi

# Summary
echo ""
echo "Summary:"
echo "$RAW" | jq -r 'select(.event == "summary") | "  \(.browser): \(.runs // 0) runs, avg \(.avgTotalMs // "-")ms total | load=\(.avgLoadMs // "-")ms dom=\(.avgDomQueryMs // "-")ms js=\(.avgJsEvalMs // "-")ms extract=\(.avgExtractMs // "-")ms | nodes=\(.avgDomNodes // "-") text=\(.avgBodyText // "-")B html=\(.avgBodyHtml // "-")B | mem: \(.memBefore // "?") → \(.memAfter // "?")"' 2>/dev/null || true

echo ""
echo "$RAW" | jq -r 'select(.event == "stats_after") | "Container Resources (after):\n" + (.stats | map("  \(.name): \(.cpu) CPU, \(.mem) RAM") | join("\n"))' 2>/dev/null || true
