# Installation Guide

## macOS

### Quick Install (Homebrew Bundle)

```bash
# Install all dependencies at once
brew bundle
```

This installs from the [Brewfile](../Brewfile):
- `python@3.12` - Python interpreter
- `rsync` - File synchronization tool
- `tmux` - Terminal multiplexer (for SSH sessions)
- `sqlite` - Database inspection tool

### Manual Install

```bash
brew install python@3.12 rsync tmux sqlite
```

### Setup

```bash
./setup.sh
poetry shell
```

---

## Linux (Debian/Ubuntu)

### Install Dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv rsync tmux sqlite3
```

### Install Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
export PATH="$HOME/.local/bin:$PATH"
```

Add to your `~/.bashrc` or `~/.profile`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Setup

```bash
./setup.sh
poetry shell
```

---

## Linux (Fedora/RHEL/CentOS)

### Install Dependencies

```bash
sudo dnf install -y python3 python3-pip rsync tmux sqlite
```

### Install Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
export PATH="$HOME/.local/bin:$PATH"
```

### Setup

```bash
./setup.sh
poetry shell
```

---

## Windows

⚠️ **Not directly supported.** This tool requires Unix symlinks and rsync.

### Option 1: WSL2 (Recommended)

Install Windows Subsystem for Linux 2, then follow the Linux instructions:

```powershell
# In PowerShell as Administrator
wsl --install -d Ubuntu
```

After WSL2 is installed, open Ubuntu and follow the Debian/Ubuntu instructions above.

### Option 2: Use the Legacy Python Tool

The [wd-mycloud-python-recovery](https://github.com/ericchapman80/wd-mycloud-python-recovery) tool may work on Windows with some limitations (no symlink farm, direct copy only).

---

## Running Commands

After setup, you have two options:

### Option A: Poetry Shell (Recommended)

```bash
# Activate the environment once
poetry shell

# Then run commands directly
python preflight.py /path/to/source /path/to/dest
python rsync_restore.py --wizard
```

### Option B: Poetry Run (No Activation)

```bash
# Run commands without activating
poetry run python preflight.py /path/to/source /path/to/dest
poetry run python rsync_restore.py --wizard
```

---

## Verify Installation

```bash
# Check Python version
python --version  # Should be 3.9+

# Check rsync
rsync --version

# Check Poetry
poetry --version

# Run preflight to test
python preflight.py --help
```
