#!/bin/bash
# Check status of all SummitFlow services (User Mode)

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "================================"
echo "SummitFlow Service Status"
echo "================================"
echo ""

ERRORS=0

# Check PostgreSQL (system service)
echo -n "PostgreSQL:    "
if systemctl is-active --quiet postgresql 2>/dev/null; then
    echo -e "${GREEN}✓ Running${NC}"
else
    echo -e "${RED}✗ Not running${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "--- SummitFlow Services (User Mode) ---"
echo ""

# Check Backend (user service)
echo -n "Backend API:   "
if systemctl --user is-active --quiet summitflow-backend.service 2>/dev/null; then
    if curl -s http://localhost:8001/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Running (http://localhost:8001)${NC}"
    else
        echo -e "${YELLOW}⚠ Running but health check failed${NC}"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "${RED}✗ Not running${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check Frontend (user service)
echo -n "Frontend:      "
if systemctl --user is-active --quiet summitflow-frontend.service 2>/dev/null; then
    if curl -s http://localhost:3001 > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Running (http://localhost:3001)${NC}"
    else
        echo -e "${YELLOW}⚠ Running but not responding${NC}"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "${RED}✗ Not running${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "--- Terminal Service (Independent) ---"
echo ""

# Check Terminal Backend (user service)
echo -n "Term Backend:  "
if systemctl --user is-active --quiet summitflow-terminal.service 2>/dev/null; then
    if curl -s http://localhost:8002/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Running (http://localhost:8002)${NC}"
    else
        echo -e "${YELLOW}⚠ Running but health check failed${NC}"
    fi
else
    echo -e "${RED}✗ Not running${NC}"
fi

# Check Terminal Frontend (user service)
echo -n "Term Frontend: "
if systemctl --user is-active --quiet summitflow-terminal-frontend.service 2>/dev/null; then
    if curl -s http://localhost:3002 > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Running (http://localhost:3002)${NC}"
    else
        echo -e "${YELLOW}⚠ Running but not responding${NC}"
    fi
else
    echo -e "${RED}✗ Not running${NC}"
fi

# Check nginx (system service)
echo ""
echo -n "nginx:         "
if systemctl is-active --quiet nginx 2>/dev/null; then
    if curl -sk https://192.168.8.233:444/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Running (https://192.168.8.233:444)${NC}"
    else
        echo -e "${YELLOW}⚠ Running (port 444 may not be configured)${NC}"
    fi
else
    echo -e "${RED}✗ Not running${NC}"
fi

echo ""
echo "================================"

if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✓ All services running${NC}"
    echo ""
    echo "URLs:"
    echo "  - Backend API:  http://localhost:8001"
    echo "  - API Docs:     http://localhost:8001/docs"
    echo "  - Frontend:     http://localhost:3001"
    echo "  - HTTPS:        https://192.168.8.233:444"
    echo "  - Terminal:     http://localhost:3002"
else
    echo -e "${RED}⚠ $ERRORS service(s) not running properly${NC}"
    echo ""
    echo "To start all services: bash ~/summitflow/scripts/start.sh"
fi

echo ""
echo "Logs (via journalctl):"
echo "  Backend:  journalctl --user -u summitflow-backend -f"
echo "  Frontend: journalctl --user -u summitflow-frontend -f"
echo "  Terminal: journalctl --user -u summitflow-terminal -f"
echo ""

exit $ERRORS
