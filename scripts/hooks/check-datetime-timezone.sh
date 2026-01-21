#!/bin/bash
#
# Pre-commit hook: Check for naive datetime patterns
# Prevents introduction of timezone-unaware datetime code
#
# Patterns detected:
# 1. datetime.now() without UTC - should be datetime.now(UTC)
# 2. datetime.utcnow() - deprecated in Python 3.12+
# 3. Column(DateTime) without timezone=True
#
# Usage:
#   ./check-datetime-timezone.sh [files...]
#   If no files specified, checks staged Python files
#

set -o pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get files to check
if [[ $# -gt 0 ]]; then
    FILES=("$@")
else
    # Check staged Python files
    mapfile -t FILES < <(git diff --cached --name-only --diff-filter=ACM | grep '\.py$')
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
    exit 0
fi

ERRORS=0
WARNINGS=0

for file in "${FILES[@]}"; do
    [[ ! -f "$file" ]] && continue

    # Skip test files (they may intentionally test naive datetimes)
    [[ "$file" == *"/tests/"* ]] && continue
    [[ "$file" == *"test_"* ]] && continue

    # Pattern 1: datetime.now() without UTC
    # Match datetime.now() but NOT datetime.now(UTC) or datetime.now(timezone.utc)
    if grep -nE 'datetime\.now\(\s*\)' "$file" >/dev/null 2>&1; then
        echo -e "${RED}ERROR${NC}: Naive datetime.now() in $file"
        grep -nE 'datetime\.now\(\s*\)' "$file" | while read -r line; do
            echo "  $line"
        done
        echo "  Fix: Use datetime.now(UTC) instead"
        ((ERRORS++))
    fi

    # Pattern 2: datetime.utcnow() - deprecated
    if grep -nE 'datetime\.utcnow\(\)' "$file" >/dev/null 2>&1; then
        echo -e "${RED}ERROR${NC}: Deprecated utcnow() in $file"
        grep -nE 'datetime\.utcnow\(\)' "$file" | while read -r line; do
            echo "  $line"
        done
        echo "  Fix: Use datetime.now(UTC) instead"
        ((ERRORS++))
    fi

    # Pattern 3: Column(DateTime) without timezone=True in SQLAlchemy models
    if grep -nE 'Column\(DateTime[^)]*\)' "$file" | grep -vE 'timezone\s*=\s*True' >/dev/null 2>&1; then
        matches=$(grep -nE 'Column\(DateTime[^)]*\)' "$file" | grep -vE 'timezone\s*=\s*True')
        if [[ -n "$matches" ]]; then
            echo -e "${YELLOW}WARNING${NC}: SQLAlchemy DateTime without timezone=True in $file"
            echo "$matches" | while read -r line; do
                echo "  $line"
            done
            echo "  Fix: Use Column(DateTime(timezone=True), ...)"
            ((WARNINGS++))
        fi
    fi
done

# Report summary
if [[ $ERRORS -gt 0 ]]; then
    echo ""
    echo -e "${RED}Found $ERRORS timezone violation(s)${NC}"
    echo "See: https://docs.python.org/3/library/datetime.html#datetime.datetime.now"
    echo ""
    echo "Required pattern: datetime.now(UTC)"
    echo "Required import: from datetime import UTC, datetime"
    exit 1
fi

if [[ $WARNINGS -gt 0 ]]; then
    echo ""
    echo -e "${YELLOW}Found $WARNINGS warning(s) - review recommended${NC}"
fi

exit 0
