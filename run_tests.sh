#!/bin/bash
# Run tests for the modern rsync-based recovery tool
# Usage:
#   ./run_tests.sh           - Run all tests with coverage
#   ./run_tests.sh html      - Generate HTML coverage report

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

MODE="${1:-all}"

case "$MODE" in
  html)
    echo -e "${BLUE}Running all tests and generating HTML coverage report...${NC}"
    poetry run pytest tests/ \
      --cov=rsync_restore \
      --cov-report=html \
      --cov-report=term \
      -v
    echo ""
    echo -e "${GREEN}✓ HTML coverage report generated in htmlcov/index.html${NC}"
    echo "Open with: open htmlcov/index.html"
    ;;
  
  all|*)
    echo -e "${BLUE}Running all tests for modern rsync-based recovery...${NC}"
    echo ""
    poetry run pytest tests/ \
      --cov=rsync_restore \
      --cov-report=term-missing \
      -v
    ;;
esac

echo ""
echo -e "${GREEN}✓ Tests completed${NC}"
echo ""
echo -e "${YELLOW}Usage:${NC}"
echo "  ./run_tests.sh           - Run all tests (default)"
echo "  ./run_tests.sh html      - Generate HTML coverage report"
