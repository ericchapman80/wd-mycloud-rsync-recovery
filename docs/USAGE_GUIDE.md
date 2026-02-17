# WD MyCloud Rsync Recovery - Usage Guide

Complete guide to recovering files from a failed WD MyCloud device using the symlink farm approach.

> **Note:** All commands assume you've activated the Poetry environment with `poetry shell`.
> Alternatively, prefix commands with `poetry run` (e.g., `poetry run python rsync_restore.py ...`).

## Overview

When a WD MyCloud device fails, your data is stored on the internal drive in a non-obvious format:

- **Files** are stored with cryptic content-based names (e.g., `a22236cwsmelmd4on2qs2jdf`)
- **Metadata** (original filenames, folder structure) is stored in a SQLite database

This tool creates a **symlink farm** - a directory tree that mirrors your original folder structure using symbolic links that point to the actual files. You can then use standard tools like `rsync` to copy your files to any destination.

## Why This Approach?

| Feature | Symlink Farm + rsync | Direct Python Copy |
|---------|---------------------|-------------------|
| Memory usage | **~50MB** (streaming) | **6-11GB** (loads all metadata) |
| Speed | Fast (rsync is optimized) | Slower (Python overhead) |
| Resumability | Built into rsync | Custom logic needed |
| Verification | rsync --checksum | Manual |
| Network issues | rsync handles retries | Can hang/crash |
| Reliability | Very stable | Can OOM on large datasets |

---

## Prerequisites

### 1. Mount Your Backup Drive

Connect the drive from your failed MyCloud device and mount it:

```bash
# Find the drive
lsblk

# Create mount point
sudo mkdir -p /mnt/backupdrive

# Mount (adjust device as needed)
sudo mount /dev/sdb4 /mnt/backupdrive
```

### 2. Verify Data Structure

Your mounted drive should have this structure:

```text
/mnt/backupdrive/
└── restsdk/
    └── data/
        ├── db/
        │   └── index.db      # SQLite database with metadata
        └── files/
            ├── 0/
            ├── 1/
            ├── a/
            ├── b/
            │   └── b4xk2m...  # Actual file data
            └── ...
```

### 3. (Optional) Mount NFS Destination

If copying to a NAS:

```bash
sudo mkdir -p /mnt/nfs-media
sudo mount -t nfs -o soft,timeo=30,retrans=3 192.168.1.100:/volume1/media /mnt/nfs-media
```

**Important:** Use `soft` mount to prevent system hangs if the NAS becomes unresponsive.

---

## Quick Start Options

### Option 1: Full Restore with Monitoring (Recommended)

```bash
python rsync_restore.py \
    --db /mnt/backupdrive/restsdk/data/db/index.db \
    --source-root /mnt/backupdrive/restsdk/data/files \
    --dest-root /mnt/nfs-media \
    --farm /tmp/restore-farm
```

This single command will:

1. ✅ Run pre-flight checks (sizes, free space, system health)
2. 🔗 Create symlink farm (if not exists)
3. 📊 Show rsync progress every 60 seconds
4. 🔄 Retry failed files (3 attempts)
5. ✅ Verify with checksums
6. 📝 Log everything to `rsync_restore.log`

### Option 2: Interactive Wizard (New Users)

```bash
python rsync_restore.py --wizard
```

The wizard will guide you through:

1. 📁 Locating your database file (index.db)
2. 📂 Locating your source files directory
3. 💾 Choosing your destination directory
4. 🔗 Setting up the symlink farm directory
5. 🔧 Configuring options (sanitize pipes, checksums, dry-run)
6. ✅ Confirmation and execution

### Option 3: Dry Run First (Preview Changes)

```bash
python rsync_restore.py \
    --db /mnt/backupdrive/restsdk/data/db/index.db \
    --source-root /mnt/backupdrive/restsdk/data/files \
    --dest-root /mnt/nfs-media \
    --farm /tmp/restore-farm \
    --dry-run
```

---

## Step-by-Step Guide

### Step 1: Run Preflight Analysis

```bash
python preflight.py /mnt/backupdrive/restsdk/data/files /mnt/nfs-media
```

This will show:
- CPU/RAM info
- Disk speeds
- Recommended thread count
- Estimated transfer time

### Step 2: Create the Symlink Farm

The symlink farm is created automatically by `rsync_restore.py`, or you can create it separately:

```bash
# Dry run first
python rsync_restore.py \
    --db /path/to/index.db \
    --source-root /path/to/files \
    --dest-root /path/to/dest \
    --farm /tmp/restore-farm \
    --dry-run
```

### Step 3: Verify the Farm Structure

Check that the symlinks look correct:

```bash
# See sample of created structure
find /tmp/restore-farm -type l | head -20

# Check a specific symlink
ls -la /tmp/restore-farm/Photos/2024/vacation.jpg
```

### Step 4: Copy Files

When ready, remove `--dry-run` to copy:

```bash
python rsync_restore.py \
    --db /path/to/index.db \
    --source-root /path/to/files \
    --dest-root /path/to/dest \
    --farm /tmp/restore-farm
```

### Step 5: Verify the Copy

```bash
# Check for differences (dry-run comparison)
rsync -avnL --checksum /tmp/restore-farm/ /mnt/nfs-media/
```

---

## Common Scenarios

### Resume an Interrupted Copy

Just run the command again - rsync will skip already-copied files:

```bash
python rsync_restore.py \
    --db /path/to/index.db \
    --source-root /path/to/files \
    --dest-root /path/to/dest \
    --farm /tmp/restore-farm
```

### Copy Only Specific Folders

```bash
rsync -avL --progress /tmp/restore-farm/Photos/ /mnt/nfs-media/Photos/
```

### Exclude Certain Files

```bash
rsync -avL --progress --exclude='*.tmp' --exclude='.DS_Store' \
    /tmp/restore-farm/ /mnt/nfs-media/
```

### Handle Pipe Characters in Filenames

Some filenames contain `|` which can cause issues on Windows/NTFS:

```bash
python rsync_restore.py --sanitize-pipes \
    --db /path/to/index.db \
    --source-root /path/to/files \
    --dest-root /path/to/dest \
    --farm /tmp/restore-farm
```

### Faster Transfer (Skip Checksum Verification)

```bash
python rsync_restore.py --no-checksum \
    --db /path/to/index.db \
    --source-root /path/to/files \
    --dest-root /path/to/dest \
    --farm /tmp/restore-farm
```

---

## Cleanup: Finding and Removing Orphaned Files

### What is an Orphan File?

An **orphan file** is a file that exists in your destination directory but does NOT have a corresponding entry in the MyCloud database. Orphans can occur from:

- **Buggy previous runs** - Earlier versions of restore scripts may have created duplicate files
- **Interrupted copies** - Partial files from failed transfers
- **Manual additions** - Files you added directly (these should be protected)

### Cleanup Workflow

```
┌─────────────────────┐     ┌─────────────────────┐
│  Wizard Mode        │     │  CLI Mode           │
│  --cleanup --wizard │     │  --cleanup --protect│
└─────────┬───────────┘     └─────────┬───────────┘
          │                           │
          └───────────┬───────────────┘
                      ▼
          ┌───────────────────────┐
          │  cleanup_rules.yaml   │
          └───────────┬───────────┘
                      ▼
          ┌───────────────────────┐
          │  Execute Cleanup      │
          │  scan, compare, delete│
          └───────────┬───────────┘
                      ▼
          ┌───────────────────────┐
          │  Summary Report       │
          └───────────────────────┘
```

### Usage Modes

**Mode 1: Interactive Wizard** (recommended for first-time cleanup)

```bash
python rsync_restore.py --cleanup --wizard
```

**Mode 2: CLI with Flags**

```bash
# Protect user folders, cleanup MyCloud folders
python rsync_restore.py --cleanup \
    --protect "my-personal-stuff/*" \
    --protect "Downloads/*" \
    --cleanup-folder "Photos/*" \
    --dry-run
```

**Mode 3: Edit Config Directly**

Create `cleanup_rules.yaml`:

```yaml
version: 1
destination: /mnt/nfs-media

# Folders to NEVER delete from (user-added content)
protect:
  - "my-personal-stuff/*"
  - "Downloads/*"

# Folders to clean orphans from (MyCloud restored content)
cleanup:
  - "Photos/*"
  - "Videos/*"
  - "Music/*"
```

Then run:

```bash
python rsync_restore.py --cleanup --config ./cleanup_rules.yaml
```

### Cleanup Safety Features

- **Dry-run by default** - Always shows what would be deleted first
- **Protected folders** - User-added folders are never touched
- **Config file** - Your choices are saved and reusable
- **Confirmation required** - Must explicitly confirm before deletion

---

## Monitoring Long-Running Operations

The `monitor.sh` script tracks system health during long recovery operations. Run it in a separate terminal to catch issues early.

### Usage

```bash
./monitor.sh [logfile] [interval] [nfs_mount] [tracking_db]
```

**Arguments:**
| Argument | Default | Description |
|----------|---------|-------------|
| `logfile` | `monitor.log` | Where to write monitoring output |
| `interval` | `30` | Seconds between checks |
| `nfs_mount` | `/mnt/nfs-media` | NFS mount point to monitor |
| `tracking_db` | (none) | Optional: SQLite DB with `copied_files` table |

### Examples

```bash
# Basic monitoring (30 second intervals)
./monitor.sh

# Custom log file and 60 second intervals
./monitor.sh recovery_monitor.log 60

# Monitor specific NFS mount
./monitor.sh monitor.log 30 /mnt/my-nas

# Run in background with nohup
nohup ./monitor.sh monitor.log 30 /mnt/nfs-media > /dev/null 2>&1 &

# Watch the log in real-time
tail -f monitor.log
```

### What It Monitors

| Metric | Description |
|--------|-------------|
| **Script status** | Is rsync/symlink/copy process running? |
| **NFS mount** | OK, UNMOUNTED, or STALLED |
| **Memory** | Usage % and MB used/total |
| **Load average** | System load (1, 5, 15 min) |
| **File descriptors** | Open FDs for Python processes |
| **I/O wait** | Disk bottleneck indicator |
| **Copied count** | Files copied (from DB or log) |

### Alerts

The script will warn you when:
- NFS mount becomes stalled or unmounted
- No copy process is running (may have crashed)
- Memory usage exceeds 90%

---

## Diagnostic Scripts

When things don't work as expected, these scripts help diagnose issues.

### Analyze Orphan Files

The `analyze_orphans.py` script helps understand why files are flagged as orphans during cleanup scans.

```bash
# Show help
python scripts/analyze_orphans.py -h

# Analyze orphans in a specific folder
python scripts/analyze_orphans.py \
    --db /mnt/backupdrive/restsdk/data/db/index.db \
    --dest /mnt/nfs-media/ \
    --folder "OSxData"

# Include source check to see if orphans exist in source
python scripts/analyze_orphans.py \
    --db /mnt/backupdrive/restsdk/data/db/index.db \
    --dest /mnt/nfs-media/ \
    --source /mnt/backupdrive/restsdk/data/files/ \
    --folder "iOSBackup" \
    --limit 50
```

**What it detects:**

- Filename encoding issues (special characters, unicode problems)
- Path mismatches (file exists but canonical path differs)
- Files that exist in dest but not in source
- Potential duplicates (same filename, different location)

### Diagnose Path Reconstruction

The `diagnose_paths.py` script compares canonical paths from the database against what actually exists in the source directory. This is critical for understanding why symlink farm creation might fail.

```bash
# Show help
python scripts/diagnose_paths.py -h

# Basic diagnosis
python scripts/diagnose_paths.py \
    --db /mnt/backupdrive/restsdk/data/db/index.db \
    --source /mnt/backupdrive/restsdk/data/files/

# With more samples
python scripts/diagnose_paths.py \
    --db /mnt/backupdrive/restsdk/data/db/index.db \
    --source /mnt/backupdrive/restsdk/data/files/ \
    --samples 200
```

**What it shows:**

- How many canonical paths actually exist in source
- Partial matches (path exists up to a certain point)
- Path format differences between DB and filesystem
- Recommendations for fixing path reconstruction issues

---

## Cleanup Configuration

### Config File Location

The cleanup rules are stored in `cleanup_rules.yaml` in your **current working directory** (where you run the command from). You can also specify a custom path:

```bash
# Use default location (./cleanup_rules.yaml)
python rsync_restore.py --cleanup --db /path/to/index.db --dest /path/to/dest

# Use custom config location
python rsync_restore.py --cleanup --config /home/user/my-cleanup-rules.yaml \
    --db /path/to/index.db --dest /path/to/dest
```

### Example Config for Your Setup

Based on your dry run output, here's a recommended config:

```yaml
# cleanup_rules.yaml
destination: /mnt/nfs-media/

# Folders to NEVER delete from (manually added, not in MyCloud DB)
protect:
  - "DisneyCruise-2025/*"
  - "TaxData/*"
  - "1and1/*"
  - "MasterServicesMaintenanceReports/*"
  # Protect these until analyzed:
  - "OSxData/*"
  - "iOSBackup/*"
  - "iPhone-Ash Camera Roll Backup/*"
  - "Eric-iPhone11-ProMax Camera Roll Backup/*"
  - "Eric-iPhone7-Plus Camera Roll Backup/*"

# Folders to clean orphans from (safe to delete duplicates)
cleanup:
  - "#recycle/*"
```

Save this file, then run:

```bash
python rsync_restore.py --cleanup \
    --db /mnt/backupdrive/restsdk/data/db/index.db \
    --dest /mnt/nfs-media/ \
    --config cleanup_rules.yaml \
    --dry-run
```

---

## Troubleshooting

### "Too many open files"

Increase file descriptor limits:

```bash
ulimit -n 65536
```

### NFS Mount Hangs

Use soft mount with timeouts:

```bash
sudo umount /mnt/nfs-media
sudo mount -t nfs -o soft,timeo=30,retrans=3 192.168.1.100:/volume1/media /mnt/nfs-media
```

### Symlinks Don't Work Across Filesystems

The farm directory must be on the same filesystem as the source files, OR you must use rsync with `-L` flag (which follows symlinks). The `rsync_restore.py` script handles this automatically.

### "Permission denied" Errors

```bash
# Check source permissions
ls -la /mnt/backupdrive/restsdk/data/files/

# Run with sudo if needed
sudo python rsync_restore.py ...
```

### Database "locked" or "unable to open"

Make sure no other process is accessing the database:

```bash
fuser /mnt/backupdrive/restsdk/data/db/index.db
```

---

## Useful rsync Flags

| Flag | Description |
|------|-------------|
| `-a` | Archive mode (preserves permissions, timestamps, owner, group) |
| `-v` | Verbose output |
| `-n` | Dry-run (preview only) |
| `-L` | Follow symlinks |
| `-X` | Preserve extended attributes (xattrs) |
| `-A` | Preserve ACLs (Access Control Lists) |
| `--progress` | Show transfer progress |
| `--checksum` | Verify with checksums (slower) |
| `--exclude` | Skip matching files |
| `--delete` | Remove extra files in destination |
| `--ignore-existing` | Skip files that already exist at destination |
| `--update` | Skip files that are newer at destination |

---

## Preserving Photo Metadata

When recovering photos, you want to preserve all metadata including EXIF data (camera info, GPS location, date taken, etc.).

### What rsync Preserves

| Metadata Type | Flag | Notes |
|---------------|------|-------|
| **EXIF data** (camera, GPS, date taken) | None needed | Embedded in file, always preserved |
| **File modification time** | `-a` | Included in archive mode |
| **File permissions** | `-a` | Included in archive mode |
| **Owner/Group** | `-a` | Included in archive mode (requires root) |
| **Extended attributes** | `-X` | macOS tags, Windows alternate streams |
| **ACLs** | `-A` | Fine-grained permissions |

### Recommended Command for Photos

```bash
# Maximum metadata preservation
rsync -avLXA --progress /tmp/restore-farm/ /mnt/nfs-media/

# Or with the script (add -X and -A manually if needed)
python rsync_restore.py \
    --db /path/to/index.db \
    --source-root /path/to/files \
    --dest-root /path/to/dest \
    --farm /tmp/restore-farm
```

### Extended Attributes (-X flag)

Extended attributes store additional metadata beyond standard file permissions:

- **macOS**: Finder tags, quarantine flags, resource forks
- **Linux**: SELinux contexts, capabilities, user-defined attributes
- **Windows**: Alternate data streams (when using Cygwin rsync)

To check if a file has extended attributes:

```bash
# macOS
xattr -l /path/to/file

# Linux
getfattr -d /path/to/file
```

### ACLs (-A flag)

Access Control Lists provide fine-grained permissions beyond the standard owner/group/other model:

```bash
# View ACLs on Linux
getfacl /path/to/file

# View ACLs on macOS
ls -le /path/to/file
```

**Note:** Both source and destination filesystems must support xattrs/ACLs for these to be preserved. NFS mounts may not support extended attributes depending on server configuration.
