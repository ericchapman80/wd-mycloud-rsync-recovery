#!/bin/bash
# setup.sh - Setup environment using Poetry (modern approach)
set -e

# Parse arguments
SKIP_SHELL_CONFIG=false
if [[ "$1" == "--no-shell-config" ]] || [[ "$1" == "--minimal" ]]; then
    SKIP_SHELL_CONFIG=true
fi

echo "🚀 Setting up Python environment with Poetry..."

# Check if Poetry is installed
if ! command -v poetry &> /dev/null; then
    echo "❌ Poetry not found. Installing via Homebrew..."
    if command -v brew &> /dev/null; then
        brew install poetry
    else
        echo "⚠️  Homebrew not found. Install Poetry manually:"
        echo "   curl -sSL https://install.python-poetry.org | python3 -"
        exit 1
    fi
fi

# Install dependencies
poetry install

# Configure UTF-8 encoding for emoji support (optional)
if [ "$SKIP_SHELL_CONFIG" = false ]; then
    echo ""
    echo "📝 Configuring UTF-8 encoding for emoji support..."
    echo "   (This will add PYTHONIOENCODING=utf-8 to your shell config)"
    echo ""
    read -p "   Modify shell config? [Y/n] " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        # Detect shell config file
        if [ -n "$ZSH_VERSION" ]; then
            SHELL_CONFIG="$HOME/.zshrc"
        elif [ -n "$BASH_VERSION" ]; then
            SHELL_CONFIG="$HOME/.bashrc"
        else
            SHELL_CONFIG="$HOME/.profile"
        fi

        # Add PYTHONIOENCODING if not already present
        if ! grep -q "PYTHONIOENCODING=utf-8" "$SHELL_CONFIG" 2>/dev/null; then
            echo "" >> "$SHELL_CONFIG"
            echo "# Python UTF-8 encoding for emoji support (added by mycloud recovery tools)" >> "$SHELL_CONFIG"
            echo "export PYTHONIOENCODING=utf-8" >> "$SHELL_CONFIG"
            echo "   ✅ Added PYTHONIOENCODING=utf-8 to $SHELL_CONFIG"
            echo ""
            echo "   ⚠️  IMPORTANT: Reload your shell or run:"
            echo "      source $SHELL_CONFIG"
        else
            echo "   ✅ PYTHONIOENCODING already configured in $SHELL_CONFIG"
        fi
    else
        echo "   ⏭️  Skipped shell config modification"
        echo "   ℹ️  Emoji output will be disabled. To enable later, run:"
        echo "      export PYTHONIOENCODING=utf-8"
        echo "   or add to your shell config manually."
    fi
else
    echo ""
    echo "⏭️  Skipped shell config modification (--no-shell-config flag)"
    echo "ℹ️  Emoji output will be disabled. To enable, set:"
    echo "   export PYTHONIOENCODING=utf-8"
fi

# Export for current session
export PYTHONIOENCODING=utf-8

echo ""
echo "🎉 Setup complete!"
echo ""
echo "You can now use:"
echo "  poetry shell"
echo ""
echo "Or run commands directly with:"
echo "  poetry run python rsync_restore.py --help"
echo "  poetry run pytest tests/"
echo ""
echo "Tip: Use ./setup.sh --no-shell-config to skip shell modifications"
