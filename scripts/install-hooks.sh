#!/bin/bash
# Install git hooks for pre-commit and pre-push testing
#
# Test organization:
#   - pre-commit: syntax + unit tests only (fast, <2s)
#   - pre-push: all unit tests (no integration, <30s)
#   - CI: full suite including integration tests with coverage

set -e

HOOKS_DIR=".git/hooks"

echo "Installing git hooks..."

# Pre-commit hook - quick syntax check and fast unit tests
cat > "$HOOKS_DIR/pre-commit" << 'EOF'
#!/bin/bash
echo "🔍 Running pre-commit checks..."

# Check Python syntax
echo "Checking Python syntax..."
poetry run python -m py_compile preflight.py rsync_restore.py
if [ $? -ne 0 ]; then
    echo "❌ Syntax errors found. Commit aborted."
    exit 1
fi

# Run unit tests only (exclude integration tests)
echo "Running quick tests..."
poetry run pytest -m "not integration" -x -q --tb=short 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ Tests failed. Commit aborted."
    exit 1
fi

echo "✅ Pre-commit checks passed!"
EOF

chmod +x "$HOOKS_DIR/pre-commit"

# Pre-push hook - all unit tests (no integration)
cat > "$HOOKS_DIR/pre-push" << 'EOF'
#!/bin/bash
echo "🔍 Running pre-push checks (full test suite)..."

# Run all unit tests (exclude integration tests for speed)
poetry run pytest -m "not integration" -v --tb=short
if [ $? -ne 0 ]; then
    echo "❌ Tests failed. Push aborted."
    exit 1
fi

echo "✅ Pre-push checks passed!"
EOF

chmod +x "$HOOKS_DIR/pre-push"

echo "✅ Git hooks installed successfully!"
echo ""
echo "Hooks installed:"
echo "  - pre-commit: syntax check + unit tests (fast)"
echo "  - pre-push: all unit tests (excludes integration)"
echo ""
echo "CI runs full suite including integration tests with coverage."
echo ""
echo "To skip hooks temporarily: git commit --no-verify"
