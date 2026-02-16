#!/bin/bash
# Install git hooks for pre-commit and pre-push testing

set -e

HOOKS_DIR=".git/hooks"

echo "Installing git hooks..."

# Pre-commit hook - quick syntax check and fast tests
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

# Run quick tests (fail fast)
echo "Running quick tests..."
poetry run pytest tests/ -x -q --tb=short 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ Tests failed. Commit aborted."
    exit 1
fi

echo "✅ Pre-commit checks passed!"
EOF

chmod +x "$HOOKS_DIR/pre-commit"

# Pre-push hook - full test suite with coverage
cat > "$HOOKS_DIR/pre-push" << 'EOF'
#!/bin/bash
echo "🔍 Running pre-push checks (full test suite)..."

# Run full test suite with coverage
poetry run pytest tests/ -v --cov=. --cov-fail-under=60
if [ $? -ne 0 ]; then
    echo "❌ Tests failed or coverage below 60%. Push aborted."
    exit 1
fi

echo "✅ Pre-push checks passed!"
EOF

chmod +x "$HOOKS_DIR/pre-push"

echo "✅ Git hooks installed successfully!"
echo ""
echo "Hooks installed:"
echo "  - pre-commit: syntax check + quick tests"
echo "  - pre-push: full test suite with 60% coverage requirement"
echo ""
echo "To skip hooks temporarily: git commit --no-verify"
