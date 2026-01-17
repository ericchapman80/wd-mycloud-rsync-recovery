# WD MyCloud Rsync Recovery

Modern rsync-based recovery toolkit for Western Digital MyCloud NAS devices. Uses battle-tested rsync with intelligent path reconstruction from SQLite database.

> **🚀 Recommended approach** for MyCloud recovery. Simpler, faster, and more reliable than SDK-based methods.

---

## Why Rsync?

- **Automatic timestamp preservation** - No separate mtime sync needed
- **Native resume capability** - Interrupted recoveries continue seamlessly  
- **Battle-tested reliability** - Decades of proven rsync stability
- **Better performance** - Optimized I/O patterns
- **Lower memory usage** - ~50 MB vs 2-10 GB (SDK approach)
- **Simpler operation** - Fewer manual steps

## Alternative: SDK Toolkit

For users who need Python API access or prefer REST SDK approach, see **[wd-mycloud-python-recovery](https://github.com/ericchapman80/wd-mycloud-python-recovery)**.

---

## Quick Start

**macOS users (install system dependencies first):**
```bash
# From repository root
brew install rsync python@3.12
```

**Setup with Poetry (recommended):**
```bash
# Standard setup (asks permission to modify shell config)
./setup.sh

# Minimal setup (no shell config modification)
./setup.sh --no-shell-config

# Reload your shell to apply UTF-8 settings (if you chose to modify)
source ~/.zshrc  # or ~/.bashrc

# Activate Poetry shell
poetry shell

# Run preflight analysis
python preflight.py /path/to/source /path/to/dest

# Run recovery
python rsync_restore.py --db index.db --source-root /source --dest-root /dest

# Monitor progress (in another terminal)
./monitor.sh
```

**Alternative: Direct commands with Poetry:**
```bash
poetry run python preflight.py /path/to/source /path/to/dest
poetry run python rsync_restore.py --db index.db --source-root /source --dest-root /dest
```

## Features

### Core Recovery
- **Multi-threaded rsync operations** for optimal performance
- **Progress monitoring** with real-time statistics
- **Automatic timestamp preservation** (no manual sync needed)
- **Resume capability** for interrupted transfers
- **Path reconstruction** from SQLite database

### Cleanup Mode
- **Orphan detection** - Find files in destination not in database
- **Pattern-based protection** - Exclude specific paths from cleanup
- **Dry-run mode** - Preview changes before deleting
- **Interactive wizard** - Guided cleanup with prompts
- **Config persistence** - Save cleanup settings

### Monitoring & Analysis
- **Preflight checks** - System analysis and recommendations
- **Thread optimization** - Automatic thread count tuning
- **Disk space warnings** - Proactive space management
- **Transfer statistics** - Detailed progress reporting

## Tools

- **rsync_restore.py** - Main recovery script (rsync wrapper with intelligent path handling)
- **preflight.py** - System analysis and thread recommendations
- **monitor.sh** - Real-time progress monitoring

## Testing

**Test Coverage:** 70-76% (467+ tests, 5,722 lines of test code)

```bash
# Run all tests
./run_tests.sh

# Run with coverage report
./run_tests.sh html

# Run specific test suites
poetry run pytest tests/test_symlink_farm.py -v          # Symlink farm tests
poetry run pytest tests/test_preflight_integration.py -v  # Integration tests
poetry run pytest tests/test_cleanup_integration.py -v    # Cleanup workflows
```

**Test Suite:**
- **Unit Tests (202 tests):** Symlink farm, preflight, cleanup, user interaction
- **Integration Tests (127 tests):** End-to-end workflows, component interaction
- **Additional Tests (60+ tests):** Progress monitoring, database operations, error handling

## Comparison: Rsync vs SDK Toolkit

| Feature | Rsync Toolkit (This) | SDK Toolkit |
|---------|---------------------|-------------|
| Timestamp Preservation | Automatic | Requires sync_mtime.py |
| Resume | Native rsync support | Limited |
| Memory Usage | ~50 MB | 2-10 GB |
| Performance | Optimized I/O | Good |
| Complexity | Lower | Higher |
| Development | Active | Open source |
| Test Coverage | 70-76% | 63% |
| API Access | No | Yes (REST SDK) |

## When to Use Which Toolkit

**Use this rsync toolkit when:**
- Starting a new recovery project (recommended)
- Want simplest operation with automatic features
- Need reliable resume capability
- Prefer battle-tested tools (rsync)
- Want active development and new features

**Use SDK toolkit when:**
- Need Python API access to MyCloud device
- Working where rsync is unavailable
- Require programmatic control over recovery
- Need symlink deduplication feature
- Prefer REST API approach

## Documentation

- **Database Schema:** [sql-data.info](sql-data.info)
- **Legacy Python Tool:** [wd-mycloud-python-recovery](https://github.com/ericchapman80/wd-mycloud-python-recovery)
- **Symlink Farm Guide:** See repository docs

## Development Status

✅ **Active Development**
- Comprehensive test suite with 70-76% coverage
- All critical workflows tested and validated
- Integration tests ensure components work together
- Regular updates and new features

## Support & Contributing

- **Issues:** Report bugs or request features via GitHub issues
- **Pull Requests:** Contributions welcome!
- **Discussions:** Use GitHub Discussions for questions
- **SDK Alternative:** [wd-mycloud-python-recovery](https://github.com/ericchapman80/wd-mycloud-python-recovery)

## License

See [LICENSE](LICENSE) file.

## Credits

Original mycloud-restsdk concept by [springfielddatarecovery](https://github.com/springfielddatarecovery/mycloud-restsdk-recovery-script)

Rsync approach, testing, and toolkit development by [@ericchapman80](https://github.com/ericchapman80)

Legacy Python tool: [wd-mycloud-python-recovery](https://github.com/ericchapman80/wd-mycloud-python-recovery)
