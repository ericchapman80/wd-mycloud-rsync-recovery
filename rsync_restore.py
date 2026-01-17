#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rsync-based restore tool with monitoring and progress tracking.

This script wraps rsync to provide:
1. Pre-flight stats (sizes, counts, free space)
2. Symlink farm creation (or verification)
3. rsync with progress parsing and monitoring
4. Retry logic for failed files
5. Comprehensive summary

Usage:
    # Full workflow with wizard
    python rsync_restore.py --wizard
    
    # Command-line mode
    python rsync_restore.py \\
        --db /mnt/backupdrive/restsdk/data/db/index.db \\
        --source /mnt/backupdrive/restsdk/data/files \\
        --dest /mnt/nfs-media \\
        --farm /tmp/restore-farm

    # Preflight only
    python rsync_restore.py --preflight-only --source /path --dest /path
"""

import argparse
import datetime
import fnmatch
import io
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

# Detect if we can safely use emoji characters
USE_EMOJI = False
try:
    # Ensure UTF-8 encoding for stdout/stderr (fixes emoji printing under sudo)
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    
    # Test if emoji can be safely encoded
    test_emoji = "✅ 📋"
    test_emoji.encode(sys.stdout.encoding)
    USE_EMOJI = True
except (UnicodeEncodeError, AttributeError, LookupError):
    # Fallback to plain text if emoji support unavailable
    USE_EMOJI = False

# Try to import yaml for config files
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# Try to import preflight for stats
try:
    from preflight import (
        get_cpu_info, get_memory_info, get_disk_info, 
        get_file_stats, disk_speed_test
    )
    HAS_PREFLIGHT = True
except ImportError:
    HAS_PREFLIGHT = False

# Try to import psutil for monitoring
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def colorize(text: str, color: str) -> str:
    """Add color to text if terminal supports it."""
    if sys.stdout.isatty():
        return f"{color}{text}{Colors.ENDC}"
    return text


def emoji(char: str, fallback: str = "") -> str:
    """Return emoji if supported, otherwise fallback text."""
    return char if USE_EMOJI else fallback


def print_header(text: str):
    print()
    print(colorize("=" * 60, Colors.CYAN))
    print(colorize(f"  {text}", Colors.BOLD + Colors.CYAN))
    print(colorize("=" * 60, Colors.CYAN))
    print()


def print_success(text: str):
    print(colorize(f"{emoji('✅', '[OK]')} {text}", Colors.GREEN))


def print_warning(text: str):
    print(colorize(f"{emoji('⚠️', '[WARN]')}  {text}", Colors.YELLOW))


def print_error(text: str):
    print(colorize(f"{emoji('❌', '[ERROR]')} {text}", Colors.RED))


def print_info(text: str):
    print(colorize(f"{emoji('ℹ️', '[INFO]')}  {text}", Colors.BLUE))


def print_step(step_num: int, text: str):
    """Print a numbered step."""
    print(colorize(f"\n{emoji('📌', '[*]')} Step {step_num}: ", Colors.BOLD + Colors.YELLOW) + text)


def prompt_path(prompt: str, must_exist: bool = True, is_dir: bool = True) -> str:
    """Prompt user for a path with validation."""
    while True:
        print()
        path = input(colorize(f"{prompt}: ", Colors.BOLD)).strip()
        
        if not path:
            print_error("Path cannot be empty. Please try again.")
            continue
        
        path = os.path.expanduser(path)
        
        if must_exist:
            if is_dir and not os.path.isdir(path):
                print_error(f"Directory not found: {path}")
                print_info("Please check the path and try again.")
                continue
            elif not is_dir and not os.path.isfile(path):
                print_error(f"File not found: {path}")
                print_info("Please check the path and try again.")
                continue
        
        return path


def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    """Prompt user for yes/no with default."""
    default_str = "[Y/n]" if default else "[y/N]"
    while True:
        response = input(colorize(f"{prompt} {default_str}: ", Colors.BOLD)).strip().lower()
        if not response:
            return default
        if response in ('y', 'yes'):
            return True
        if response in ('n', 'no'):
            return False
        print_error("Please enter 'y' or 'n'")


def format_bytes(n: int) -> str:
    """Format bytes in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(n) < 1024.0:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"


def format_number(n: int) -> str:
    """Format number with commas."""
    return f"{n:,}"


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        mins, secs = divmod(int(seconds), 60)
        return f"{mins}m {secs}s"
    else:
        hours, remainder = divmod(int(seconds), 3600)
        mins, secs = divmod(remainder, 60)
        return f"{hours}h {mins}m {secs}s"


# ============================================================================
# CLEANUP FEATURE: Config file and orphan detection
# ============================================================================

DEFAULT_CLEANUP_CONFIG = {
    'version': 1,
    'destination': '',
    'protect': [],
    'cleanup': [],
    'keep_files': [],
    'last_scan': None,
    'orphans_found': 0,
    'orphans_deleted': 0,
}


def load_cleanup_config(config_path: str) -> Dict:
    """Load cleanup configuration from YAML file."""
    if not os.path.exists(config_path):
        return DEFAULT_CLEANUP_CONFIG.copy()
    
    if not HAS_YAML:
        print_warning("PyYAML not installed. Using simple config parser.")
        return _load_simple_config(config_path)
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Merge with defaults
    result = DEFAULT_CLEANUP_CONFIG.copy()
    if config:
        result.update(config)
    return result


def save_cleanup_config(config: Dict, config_path: str):
    """Save cleanup configuration to YAML file."""
    config['last_scan'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if HAS_YAML:
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    else:
        _save_simple_config(config, config_path)
    
    print_success(f"Config saved to: {config_path}")


def _load_simple_config(config_path: str) -> Dict:
    """Simple config loader when PyYAML is not available."""
    config = DEFAULT_CLEANUP_CONFIG.copy()
    with open(config_path, 'r') as f:
        for line in f:
            line = line.strip()
            if ':' in line and not line.startswith('#'):
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key in config:
                    if isinstance(config[key], list):
                        if value:
                            config[key].append(value)
                    else:
                        config[key] = value
    return config


def _save_simple_config(config: Dict, config_path: str):
    """Simple config saver when PyYAML is not available."""
    with open(config_path, 'w') as f:
        f.write("# Cleanup configuration\n")
        f.write(f"version: {config.get('version', 1)}\n")
        f.write(f"destination: {config.get('destination', '')}\n")
        f.write(f"last_scan: {config.get('last_scan', '')}\n")
        f.write(f"orphans_found: {config.get('orphans_found', 0)}\n")
        f.write(f"orphans_deleted: {config.get('orphans_deleted', 0)}\n")
        f.write("\n# Folders to protect (never delete from)\n")
        for p in config.get('protect', []):
            f.write(f"protect: {p}\n")
        f.write("\n# Folders to cleanup (remove orphans from)\n")
        for c in config.get('cleanup', []):
            f.write(f"cleanup: {c}\n")


def matches_pattern(path: str, patterns: List[str]) -> bool:
    """Check if path matches any of the glob patterns."""
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        # Also check if any parent directory matches
        parts = path.split(os.sep)
        for i in range(len(parts)):
            partial = os.sep.join(parts[:i+1])
            if fnmatch.fnmatch(partial, pattern.rstrip('/*')):
                return True
    return False


def get_canonical_paths_from_db(db_path: str) -> Set[str]:
    """
    Get all canonical file paths from the database.
    Returns a set of relative paths that should exist in destination.
    """
    print_info("Loading canonical paths from database...")
    canonical_paths = set()
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Build parent lookup
        cur.execute("SELECT id, name, parentID FROM files")
        parent_lookup = {}
        for row in cur:
            parent_lookup[row['id']] = (row['name'], row['parentID'])
        
        # Find root dir to strip
        cur.execute("SELECT name FROM files WHERE name LIKE '%auth%|%' LIMIT 1")
        row = cur.fetchone()
        root_dir = row['name'] if row else None
        
        # Get all files with contentID
        cur.execute("SELECT id, name, parentID FROM files WHERE contentID IS NOT NULL")
        
        for row in cur:
            # Reconstruct path
            path_parts = [row['name']]
            current_id = row['parentID']
            while current_id and current_id in parent_lookup:
                name, parent_id = parent_lookup[current_id]
                path_parts.insert(0, name)
                current_id = parent_id
            
            rel_path = '/'.join(path_parts)
            
            # Strip root dir
            if root_dir:
                rel_path = rel_path.replace(root_dir + '/', '').replace(root_dir, '')
            rel_path = rel_path.lstrip('/')
            
            if rel_path:
                canonical_paths.add(rel_path)
    
    print_success(f"Loaded {format_number(len(canonical_paths))} canonical paths")
    return canonical_paths


def scan_destination_for_orphans(
    dest_dir: str,
    canonical_paths: Set[str],
    protect_patterns: List[str],
    cleanup_patterns: List[str]
) -> Dict[str, List[str]]:
    """
    Scan destination directory and identify orphan files.
    
    Returns dict with keys:
        - 'orphans': list of orphan file paths
        - 'protected': list of files in protected folders
        - 'matched': list of files matching canonical paths
        - 'by_folder': dict of folder -> orphan list
    """
    print_info(f"Scanning destination: {dest_dir}")
    
    results = {
        'orphans': [],
        'protected': [],
        'matched': [],
        'by_folder': {},
        'folder_stats': {},  # folder -> {'total': N, 'orphans': N, 'in_db': bool}
    }
    
    # Track top-level folders
    top_level_folders = set()
    
    file_count = 0
    for root, dirs, files in os.walk(dest_dir):
        for filename in files:
            file_count += 1
            if file_count % 10000 == 0:
                print(f"  Scanned {format_number(file_count)} files...")
            
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, dest_dir)
            
            # Get top-level folder
            top_folder = rel_path.split(os.sep)[0] if os.sep in rel_path else ''
            if top_folder:
                top_level_folders.add(top_folder)
            
            # Initialize folder stats
            if top_folder and top_folder not in results['folder_stats']:
                results['folder_stats'][top_folder] = {
                    'total': 0,
                    'orphans': 0,
                    'matched': 0,
                    'in_db': False
                }
            
            if top_folder:
                results['folder_stats'][top_folder]['total'] += 1
            
            # Check if protected
            if matches_pattern(rel_path, protect_patterns):
                results['protected'].append(rel_path)
                continue
            
            # Check if in canonical paths
            # Normalize path separators for comparison
            normalized_path = rel_path.replace(os.sep, '/')
            if normalized_path in canonical_paths:
                results['matched'].append(rel_path)
                if top_folder:
                    results['folder_stats'][top_folder]['matched'] += 1
                    results['folder_stats'][top_folder]['in_db'] = True
                continue
            
            # It's an orphan
            results['orphans'].append(rel_path)
            if top_folder:
                results['folder_stats'][top_folder]['orphans'] += 1
                if top_folder not in results['by_folder']:
                    results['by_folder'][top_folder] = []
                results['by_folder'][top_folder].append(rel_path)
    
    print_success(f"Scanned {format_number(file_count)} files")
    print_info(f"  Matched: {format_number(len(results['matched']))}")
    print_info(f"  Orphans: {format_number(len(results['orphans']))}")
    print_info(f"  Protected: {format_number(len(results['protected']))}")
    
    return results


def delete_orphans(
    dest_dir: str,
    orphan_paths: List[str],
    dry_run: bool = True
) -> Tuple[int, int]:
    """
    Delete orphan files from destination.
    
    Returns (deleted_count, error_count)
    """
    deleted = 0
    errors = 0
    
    for rel_path in orphan_paths:
        full_path = os.path.join(dest_dir, rel_path)
        
        if dry_run:
            print(f"  [DRY-RUN] Would delete: {rel_path}")
            deleted += 1
        else:
            try:
                os.remove(full_path)
                deleted += 1
            except OSError as e:
                print_warning(f"  Failed to delete {rel_path}: {e}")
                errors += 1
    
    return deleted, errors


def run_cleanup_wizard(
    dest_dir: str,
    db_path: str,
    config_path: str = 'cleanup_rules.yaml'
) -> int:
    """Run interactive cleanup wizard."""
    print_header("Cleanup Wizard")
    
    # Load existing config
    config = load_cleanup_config(config_path)
    config['destination'] = dest_dir
    
    # Get canonical paths from DB
    canonical_paths = get_canonical_paths_from_db(db_path)
    
    # Scan destination
    scan_results = scan_destination_for_orphans(
        dest_dir,
        canonical_paths,
        config.get('protect', []),
        config.get('cleanup', [])
    )
    
    # Show summary by folder
    print_header("Folder Summary")
    
    folders_to_review = []
    for folder, stats in sorted(scan_results['folder_stats'].items()):
        in_db = "FROM: MyCloud" if stats['in_db'] else "NOT in DB"
        orphan_count = stats['orphans']
        
        status = "✅" if orphan_count == 0 else "⚠️ "
        print(f"  {status} {folder}/")
        print(f"      {format_number(stats['total'])} files | {format_number(orphan_count)} orphans | {in_db}")
        
        if orphan_count > 0 or not stats['in_db']:
            folders_to_review.append(folder)
    
    if not folders_to_review:
        print_success("No orphans found! Destination is clean.")
        return 0
    
    # Interactive folder classification
    print_header("Classify Folders")
    
    for folder in folders_to_review:
        stats = scan_results['folder_stats'][folder]
        in_db = stats['in_db']
        orphan_count = stats['orphans']
        
        print()
        if not in_db:
            print(f"📁 '{folder}/' is NOT in MyCloud database.")
            print("   This may be a folder you added manually.")
        else:
            print(f"📁 '{folder}/' has {format_number(orphan_count)} orphan files.")
            if folder in scan_results['by_folder']:
                examples = scan_results['by_folder'][folder][:3]
                print("   Examples:")
                for ex in examples:
                    print(f"     - {ex}")
        
        print()
        print("  [P]rotect (never delete)  [C]leanup (delete orphans)  [S]kip for now")
        
        while True:
            response = input(colorize("  Your choice: ", Colors.BOLD)).strip().upper()
            if response == 'P':
                pattern = f"{folder}/*"
                if pattern not in config['protect']:
                    config['protect'].append(pattern)
                print_success(f"  Added '{pattern}' to protected list")
                break
            elif response == 'C':
                pattern = f"{folder}/*"
                if pattern not in config['cleanup']:
                    config['cleanup'].append(pattern)
                print_success(f"  Added '{pattern}' to cleanup list")
                break
            elif response == 'S':
                print_info("  Skipped")
                break
            else:
                print_error("  Please enter P, C, or S")
    
    # Save config
    save_cleanup_config(config, config_path)
    
    # Calculate orphans to delete (only from cleanup folders)
    orphans_to_delete = []
    for orphan in scan_results['orphans']:
        if matches_pattern(orphan, config['cleanup']) and not matches_pattern(orphan, config['protect']):
            orphans_to_delete.append(orphan)
    
    if not orphans_to_delete:
        print_success("No orphans to delete after applying rules.")
        return 0
    
    # Confirm deletion
    print_header("Confirm Deletion")
    print(f"Ready to delete {format_number(len(orphans_to_delete))} orphan files.")
    print()
    
    # Show some examples
    print("Examples:")
    for orphan in orphans_to_delete[:5]:
        print(f"  - {orphan}")
    if len(orphans_to_delete) > 5:
        print(f"  ... and {len(orphans_to_delete) - 5} more")
    
    print()
    if not prompt_yes_no("Delete these files?", default=False):
        print_info("Deletion cancelled. Config saved for future use.")
        return 0
    
    # Delete orphans
    print_header("Deleting Orphans")
    deleted, errors = delete_orphans(dest_dir, orphans_to_delete, dry_run=False)
    
    config['orphans_found'] = len(scan_results['orphans'])
    config['orphans_deleted'] = deleted
    save_cleanup_config(config, config_path)
    
    print_header("Cleanup Summary")
    print(f"  Deleted: {format_number(deleted)}")
    print(f"  Errors:  {format_number(errors)}")
    
    return 0 if errors == 0 else 1


def run_cleanup_cli(
    dest_dir: str,
    db_path: str,
    config_path: str,
    protect_patterns: List[str],
    cleanup_patterns: List[str],
    dry_run: bool = True,
    auto_yes: bool = False
) -> int:
    """Run cleanup from command-line arguments."""
    print_header("Cleanup Mode")
    
    # Load and merge config
    config = load_cleanup_config(config_path)
    config['destination'] = dest_dir
    
    # Add CLI patterns to config
    for p in protect_patterns:
        if p not in config['protect']:
            config['protect'].append(p)
    for c in cleanup_patterns:
        if c not in config['cleanup']:
            config['cleanup'].append(c)
    
    # Get canonical paths from DB
    canonical_paths = get_canonical_paths_from_db(db_path)
    
    # Scan destination
    scan_results = scan_destination_for_orphans(
        dest_dir,
        canonical_paths,
        config['protect'],
        config['cleanup']
    )
    
    # Calculate orphans to delete
    orphans_to_delete = []
    for orphan in scan_results['orphans']:
        # Only delete if in cleanup folders and not protected
        if config['cleanup']:
            if matches_pattern(orphan, config['cleanup']) and not matches_pattern(orphan, config['protect']):
                orphans_to_delete.append(orphan)
        else:
            # If no cleanup patterns, delete all non-protected orphans
            if not matches_pattern(orphan, config['protect']):
                orphans_to_delete.append(orphan)
    
    if not orphans_to_delete:
        print_success("No orphans to delete.")
        return 0
    
    print_info(f"Found {format_number(len(orphans_to_delete))} orphans to delete")
    
    if dry_run:
        print_header("Dry Run - Would Delete")
        deleted, _ = delete_orphans(dest_dir, orphans_to_delete, dry_run=True)
        print()
        print_info(f"Dry run complete. Would delete {format_number(deleted)} files.")
        print_info("Run without --dry-run to actually delete.")
        return 0
    
    # Confirm
    if not auto_yes:
        if not prompt_yes_no(f"Delete {format_number(len(orphans_to_delete))} orphan files?", default=False):
            print_info("Cancelled.")
            return 0
    
    # Delete
    deleted, errors = delete_orphans(dest_dir, orphans_to_delete, dry_run=False)
    
    config['orphans_found'] = len(scan_results['orphans'])
    config['orphans_deleted'] = deleted
    save_cleanup_config(config, config_path)
    
    print_header("Cleanup Complete")
    print(f"  Deleted: {format_number(deleted)}")
    print(f"  Errors:  {format_number(errors)}")
    
    return 0 if errors == 0 else 1


def get_db_stats(db_path: str) -> Dict:
    """Get file statistics from the database."""
    stats = {
        'total_files': 0,
        'total_dirs': 0,
        'copied_files': 0,
        'skipped_files': 0,
    }
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        cur = conn.cursor()
        
        # Total files (entries with contentID)
        # Use Files (capital F) to match production schema
        cur.execute("SELECT COUNT(*) FROM Files WHERE contentID IS NOT NULL AND contentID != ''")
        stats['total_files'] = cur.fetchone()[0]
        
        # Total directories (entries without contentID or empty contentID)
        cur.execute("SELECT COUNT(*) FROM Files WHERE contentID IS NULL OR contentID = ''")
        stats['total_dirs'] = cur.fetchone()[0]
        
        # Note: copied_files and skipped_files tables are for legacy Python tool tracking
        # The rsync approach doesn't use these tables, so don't report misleading "already copied" stats
        # Just show what needs to be recovered
    
    stats['remaining'] = stats['total_files']  # All files need recovery for fresh run
    stats['percent_complete'] = 0  # Start from 0% for rsync recovery
    
    return stats


def count_files_in_dir(path: str) -> Tuple[int, int]:
    """Count files and get total size in a directory."""
    total_files = 0
    total_size = 0
    for root, dirs, files in os.walk(path):
        total_files += len(files)
        for f in files:
            try:
                total_size += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total_files, total_size


def run_preflight(source: str, dest: str, db_path: Optional[str] = None, farm: Optional[str] = None) -> Dict:
    """Run preflight checks and gather statistics."""
    print_header("Pre-flight Checks")
    
    results = {
        'source': source,
        'dest': dest,
        'db_path': db_path,
        'farm': farm,
        'checks_passed': True,
        'warnings': [],
    }
    
    # Check source exists
    if os.path.isdir(source):
        print_success(f"Source directory exists: {source}")
        src_files, src_size = count_files_in_dir(source)
        results['source_files'] = src_files
        results['source_size'] = src_size
        print_info(f"  Files: {format_number(src_files)} | Size: {format_bytes(src_size)}")
    else:
        print_error(f"Source directory not found: {source}")
        results['checks_passed'] = False
        return results
    
    # Check destination
    if os.path.isdir(dest):
        print_success(f"Destination directory exists: {dest}")
        dest_files, dest_size = count_files_in_dir(dest)
        results['dest_files'] = dest_files
        results['dest_size'] = dest_size
        print_info(f"  Files: {format_number(dest_files)} | Size: {format_bytes(dest_size)}")
        
        # Check free space
        if HAS_PSUTIL:
            usage = psutil.disk_usage(dest)
            results['dest_free'] = usage.free
            print_info(f"  Free space: {format_bytes(usage.free)}")
            
            # Warn if free space is low
            estimated_remaining = src_size - dest_size
            if estimated_remaining > 0 and usage.free < estimated_remaining * 1.1:
                print_warning(f"Low free space! May need {format_bytes(estimated_remaining)}")
                results['warnings'].append('low_free_space')
    else:
        print_warning(f"Destination directory will be created: {dest}")
        results['dest_files'] = 0
        results['dest_size'] = 0
    
    # Check database
    if db_path:
        if os.path.isfile(db_path):
            print_success(f"Database found: {db_path}")
            db_stats = get_db_stats(db_path)
            results['db_stats'] = db_stats
            print_info(f"  Total files in DB: {format_number(db_stats['total_files'])}")
            print_info(f"  Files to recover: {format_number(db_stats['remaining'])}")
        else:
            print_error(f"Database not found: {db_path}")
            results['checks_passed'] = False
    
    # Check symlink farm
    if farm:
        if os.path.isdir(farm):
            farm_files, _ = count_files_in_dir(farm)
            print_success(f"Symlink farm exists: {farm}")
            print_info(f"  Symlinks: {format_number(farm_files)}")
            results['farm_files'] = farm_files
        else:
            print_info(f"Symlink farm will be created: {farm}")
            results['farm_files'] = 0
    
    # Check rsync
    rsync_path = shutil.which('rsync')
    if rsync_path:
        print_success(f"rsync found: {rsync_path}")
        results['rsync_path'] = rsync_path
    else:
        print_error("rsync not found! Please install rsync.")
        results['checks_passed'] = False
    
    # System stats
    if HAS_PSUTIL:
        mem = psutil.virtual_memory()
        print_info(f"Memory: {mem.percent:.1f}% used ({format_bytes(mem.available)} available)")
        results['memory_percent'] = mem.percent
        results['memory_available'] = mem.available
        
        load = os.getloadavg()
        print_info(f"Load average: {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}")
        results['load_avg'] = load
    
    return results


class RsyncMonitor:
    """Monitor rsync progress and system health."""
    
    def __init__(self, log_file: str, log_interval: int = 60):
        self.log_file = log_file
        self.log_interval = log_interval
        self.running = False
        self.thread = None
        self.start_time = None
        
        # Progress tracking
        self.bytes_transferred = 0
        self.files_transferred = 0
        self.percent_complete = 0
        self.transfer_speed = 0
        self.eta = ""
        self.current_file = ""
        self.errors: List[str] = []
        
        # Lock for thread-safe updates
        self.lock = threading.Lock()
    
    def start(self):
        """Start the monitoring thread."""
        self.running = True
        self.start_time = time.time()
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        
        # Write header to log file
        with open(self.log_file, 'a') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"rsync restore started: {datetime.datetime.now()}\n")
            f.write(f"{'='*60}\n\n")
    
    def stop(self):
        """Stop the monitoring thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
    
    def update_progress(self, bytes_transferred: int = None, files_transferred: int = None,
                       percent: float = None, speed: float = None, eta: str = None,
                       current_file: str = None):
        """Update progress from rsync output parsing."""
        with self.lock:
            if bytes_transferred is not None:
                self.bytes_transferred = bytes_transferred
            if files_transferred is not None:
                self.files_transferred = files_transferred
            if percent is not None:
                self.percent_complete = percent
            if speed is not None:
                self.transfer_speed = speed
            if eta is not None:
                self.eta = eta
            if current_file is not None:
                self.current_file = current_file
    
    def add_error(self, error: str):
        """Record an error."""
        with self.lock:
            self.errors.append(error)
    
    def _monitor_loop(self):
        """Background monitoring loop."""
        while self.running:
            self._log_status()
            time.sleep(self.log_interval)
    
    def _log_status(self):
        """Log current status to file and stdout."""
        elapsed = time.time() - self.start_time if self.start_time else 0
        
        # Get system stats
        mem_pct = "N/A"
        load = "N/A"
        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            mem_pct = f"{mem.percent:.1f}%"
            load_avg = os.getloadavg()
            load = f"{load_avg[0]:.2f} {load_avg[1]:.2f} {load_avg[2]:.2f}"
        
        with self.lock:
            status_line = (
                f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"Files: {format_number(self.files_transferred)} | "
                f"Data: {format_bytes(self.bytes_transferred)} | "
                f"{self.percent_complete:.1f}% | "
                f"Speed: {format_bytes(int(self.transfer_speed))}/s | "
                f"ETA: {self.eta} | "
                f"Mem: {mem_pct} | "
                f"Load: {load}"
            )
        
        print(status_line)
        
        with open(self.log_file, 'a') as f:
            f.write(status_line + '\n')


def parse_rsync_progress(line: str, monitor: RsyncMonitor):
    """Parse rsync -v --progress output and update monitor."""
    # Standard --progress format:
    #   "       1,234,567  45%   12.34MB/s    0:01:23"
    # File transfer lines:
    #   "path/to/file.txt"
    # Verbose summary:
    #   "sent 1,234 bytes  received 5,678 bytes  1,234.56 bytes/sec"
    #   "total size is 123,456,789  speedup is 1.23"
    
    # Match progress line: "     123,456  45%  1.23MB/s    0:01:23"
    progress_match = re.search(
        r'^\s*([\d,]+)\s+(\d+)%\s+([\d.]+)([KMG]?)B/s\s+(\d+:\d+:\d+)',
        line
    )
    
    if progress_match:
        bytes_str = progress_match.group(1).replace(',', '')
        percent = int(progress_match.group(2))
        speed_num = float(progress_match.group(3))
        speed_unit = progress_match.group(4)
        eta = progress_match.group(5)
        
        # Convert speed to bytes/s
        speed_multiplier = {'': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3}
        speed = speed_num * speed_multiplier.get(speed_unit, 1)
        
        monitor.update_progress(
            bytes_transferred=int(bytes_str),
            percent=percent,
            speed=speed,
            eta=eta
        )
    
    # Parse rsync final summary for accurate totals
    # "total size is 451,234,567  speedup is 1.00"
    total_match = re.search(r'total size is ([\d,]+)', line)
    if total_match:
        total_bytes = int(total_match.group(1).replace(',', ''))
        with monitor.lock:
            monitor.bytes_transferred = total_bytes
    
    # Count only actual file transfers (lines with "xfr#N" in progress output)
    # This appears when rsync transfers a file
    xfr_match = re.search(r'xfr#(\d+)', line)
    if xfr_match:
        file_num = int(xfr_match.group(1))
        with monitor.lock:
            monitor.files_transferred = file_num
            # Extract filename from line if present
            if '(' in line:
                filename = line.split('(')[0].strip()
                if filename:
                    monitor.current_file = filename
    
    # Check for errors
    if 'error' in line.lower() or 'failed' in line.lower():
        monitor.add_error(line.strip())


def run_rsync(
    source: str,
    dest: str,
    monitor: RsyncMonitor,
    checksum: bool = True,
    dry_run: bool = False,
    delete: bool = False,
    exclude: List[str] = None
) -> Tuple[int, List[str]]:
    """
    Run rsync with progress monitoring.
    
    Returns:
        Tuple of (return_code, list_of_errors)
    """
    # Build rsync command
    # Use --progress for real-time feedback (works on all rsync versions)
    cmd = ['rsync', '-avL', '--progress']
    
    if checksum:
        cmd.append('--checksum')
    
    if dry_run:
        cmd.append('--dry-run')
    
    if delete:
        cmd.append('--delete')
    
    if exclude:
        for pattern in exclude:
            cmd.extend(['--exclude', pattern])
    
    # Ensure source ends with / to copy contents
    if not source.endswith('/'):
        source = source + '/'
    
    cmd.extend([source, dest])
    
    print_info(f"Running: {' '.join(cmd)}")
    print()
    
    errors = []
    last_file_print = 0
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            errors='replace'  # Replace invalid UTF-8 chars instead of failing
        )
        
        for line in process.stdout:
            line = line.strip()
            if line:
                parse_rsync_progress(line, monitor)
                
                # Print file transfer updates periodically (every 5 actual file transfers)
                if monitor.files_transferred > 0 and monitor.files_transferred % 5 == 0 and \
                   monitor.files_transferred != last_file_print:
                    filename = monitor.current_file if monitor.current_file else "..."
                    prefix = emoji('📋', '[TRANSFER]')
                    print(f"  {prefix} [{monitor.files_transferred} files] {filename}")
                    last_file_print = monitor.files_transferred
                
                # Check for errors
                if 'error' in line.lower() or 'failed' in line.lower():
                    errors.append(line)
                    print_warning(line)
        
        process.wait()
        return process.returncode, errors
        
    except KeyboardInterrupt:
        print_warning("\nInterrupted by user")
        process.terminate()
        return 130, errors
    except Exception as e:
        print_error(f"rsync failed: {e}")
        errors.append(str(e))
        return 1, errors


def create_symlink_farm_streaming(
    db_path: str,
    source_dir: str,
    farm_dir: str,
    sanitize_pipes: bool = False,
    limit: int = 0
) -> Tuple[int, int, int]:
    """
    Create symlink farm by streaming from database (minimal memory).
    
    Args:
        limit: Process only first N files (0 = no limit)
    
    Returns:
        Tuple of (created, skipped, errors)
    """
    print_info("Creating symlink farm (streaming from database)...")
    if limit > 0:
        print_warning(f"⚠️  Testing mode: Processing only {limit} files (--limit={limit})")
    
    created = 0
    skipped = 0
    errors = 0
    
    os.makedirs(farm_dir, exist_ok=True)
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Get total count for progress
        cur.execute("SELECT COUNT(*) FROM files WHERE contentID IS NOT NULL")
        total = cur.fetchone()[0]
        
        # Find root dir to strip
        cur.execute("SELECT name FROM files WHERE name LIKE '%auth%|%' LIMIT 1")
        row = cur.fetchone()
        root_dir = row['name'] if row else None
        
        # Stream files and create symlinks
        cur.execute("""
            SELECT id, name, parentID, contentID 
            FROM files 
            WHERE contentID IS NOT NULL
        """)
        
        # Build minimal parent lookup (just id -> name, parent)
        parent_lookup = {}
        cur2 = conn.cursor()
        cur2.execute("SELECT id, name, parentID FROM files")
        for row in cur2:
            parent_lookup[row['id']] = (row['name'], row['parentID'])
        
        processed = 0
        last_progress = 0
        
        for row in cur:
            # Check limit
            if limit > 0 and created >= limit:
                print_warning(f"\n⚠️  Reached --limit of {limit} files. Stopping...")
                break
            
            processed += 1
            
            # Progress every 5%
            pct = int(processed / total * 100)
            if pct >= last_progress + 5:
                print(f"  Progress: {pct}% ({format_number(processed)}/{format_number(total)})")
                last_progress = pct
            
            content_id = row['contentID']
            file_id = row['id']
            
            # Reconstruct path
            path_parts = [row['name']]
            current_id = row['parentID']
            while current_id and current_id in parent_lookup:
                name, parent_id = parent_lookup[current_id]
                path_parts.insert(0, name)
                current_id = parent_id
            
            rel_path = '/'.join(path_parts)
            
            # Strip root dir
            if root_dir:
                rel_path = rel_path.replace(root_dir + '/', '').replace(root_dir, '')
            rel_path = rel_path.lstrip('/')
            
            if sanitize_pipes:
                rel_path = rel_path.replace('|', '-')
            
            if not rel_path:
                skipped += 1
                continue
            
            # Find source file
            source_path = None
            for candidate in [
                os.path.join(source_dir, content_id[0], content_id),
                os.path.join(source_dir, content_id)
            ]:
                if os.path.exists(candidate):
                    source_path = candidate
                    break
            
            if not source_path:
                skipped += 1
                continue
            
            # Create symlink (use absolute path to avoid broken symlinks)
            farm_path = os.path.join(farm_dir, rel_path)
            abs_source_path = os.path.abspath(source_path)
            
            try:
                os.makedirs(os.path.dirname(farm_path), exist_ok=True)
                
                if os.path.islink(farm_path):
                    os.remove(farm_path)
                elif os.path.exists(farm_path):
                    skipped += 1
                    continue
                
                os.symlink(abs_source_path, farm_path)
                created += 1
                
            except OSError as e:
                errors += 1
        
        # Clear parent lookup to free memory
        del parent_lookup
    
    print_success(f"Created {format_number(created)} symlinks")
    if skipped > 0:
        print_info(f"Skipped {format_number(skipped)} (no source or duplicate)")
    if errors > 0:
        print_warning(f"Errors: {format_number(errors)}")
    
    return created, skipped, errors


def run_restore(
    db_path: str,
    source: str,
    dest: str,
    farm: str,
    checksum: bool = True,
    dry_run: bool = False,
    retry_count: int = 3,
    log_interval: int = 60,
    log_file: str = "rsync_restore.log",
    sanitize_pipes: bool = False,
    skip_farm: bool = False,
    limit: int = 0
) -> int:
    """
    Run the full restore process.
    
    Args:
        limit: Process only first N files (0 = no limit)
    
    Returns:
        Exit code (0 = success)
    """
    start_time = time.time()
    
    # Preflight checks
    preflight = run_preflight(source, dest, db_path, farm)
    if not preflight['checks_passed']:
        print_error("Pre-flight checks failed. Please fix the issues above.")
        return 1
    
    # Create/verify symlink farm
    if not skip_farm:
        print_header("Symlink Farm")
        
        if os.path.isdir(farm) and os.listdir(farm):
            farm_files, _ = count_files_in_dir(farm)
            print_info(f"Existing farm found with {format_number(farm_files)} symlinks")
            
            # Check if farm is up to date
            if 'db_stats' in preflight:
                expected = preflight['db_stats']['total_files']
                if farm_files < expected * 0.9:
                    print_warning(f"Farm may be incomplete (expected ~{format_number(expected)})")
                    response = input("Rebuild farm? [y/N]: ").strip().lower()
                    if response == 'y':
                        print_info("Removing old farm...")
                        shutil.rmtree(farm)
                        created, skipped, errors = create_symlink_farm_streaming(
                            db_path, source, farm, sanitize_pipes, limit
                        )
        else:
            created, skipped, errors = create_symlink_farm_streaming(
                db_path, source, farm, sanitize_pipes, limit
            )
    else:
        print_info("Skipping symlink farm (--skip-farm)")
    
    # Start monitoring
    print_header("Starting rsync")
    monitor = RsyncMonitor(log_file, log_interval)
    monitor.start()
    
    try:
        # Run rsync
        return_code, errors = run_rsync(
            source=farm,
            dest=dest,
            monitor=monitor,
            checksum=checksum,
            dry_run=dry_run
        )
        
        # Retry failed files if any
        if errors and retry_count > 0 and not dry_run:
            print_header(f"Retrying {len(errors)} failed items")
            for attempt in range(retry_count):
                print_info(f"Retry attempt {attempt + 1}/{retry_count}")
                return_code, errors = run_rsync(
                    source=farm,
                    dest=dest,
                    monitor=monitor,
                    checksum=checksum,
                    dry_run=False
                )
                if not errors:
                    print_success("All retries successful")
                    break
        
    finally:
        monitor.stop()
    
    # Summary
    elapsed = time.time() - start_time
    
    # Get final counts
    source_files, source_size = count_files_in_dir(source)
    dest_files, dest_size = count_files_in_dir(dest)
    
    print_header("Summary")
    print()
    print(f"  Source:        {source_files} files | {format_bytes(source_size)}")
    print(f"  Destination:   {dest_files} files | {format_bytes(dest_size)}")
    print()
    print(f"  Started:       {datetime.datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Finished:      {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Duration:      {format_duration(elapsed)}")
    print()
    print(f"  Files transferred: {format_number(monitor.files_transferred)}")
    print(f"  Data transferred:  {format_bytes(monitor.bytes_transferred)}")
    
    if elapsed > 0 and monitor.bytes_transferred > 0:
        avg_speed = monitor.bytes_transferred / elapsed
        print(f"  Average speed:     {format_bytes(int(avg_speed))}/s")
    
    print()
    if monitor.errors:
        print_warning(f"  Errors:            {len(monitor.errors)}")
        print()
        print("  Error details:")
        for err in monitor.errors[:10]:
            print(f"    - {err}")
        if len(monitor.errors) > 10:
            print(f"    ... and {len(monitor.errors) - 10} more (see {log_file})")
    else:
        print_success("  Errors:            0")
    
    print()
    print_info(f"Full log written to: {log_file}")
    
    return 0 if return_code == 0 and not monitor.errors else 1


def run_wizard() -> int:
    """Run interactive wizard mode."""
    print_header("rsync Restore Wizard")
    
    # Check rsync
    rsync_path = shutil.which('rsync')
    if not rsync_path:
        print_error("rsync is not installed!")
        print("""
rsync is required to copy files. Please install it:
  macOS:    brew install rsync
  Ubuntu:   sudo apt install rsync
  Fedora:   sudo dnf install rsync
""")
        return 1
    print_success(f"rsync found: {rsync_path}")
    
    print("""
This wizard will guide you through restoring files from a WD MyCloud
backup using the symlink farm + rsync approach.

This method uses minimal memory and is very reliable.
""")
    
    # Step 1: Database
    print_step(1, "Locate your MyCloud database")
    print("""
The database file is usually named 'index.db' and located at:
  /mnt/backupdrive/restsdk/data/db/index.db
""")
    db_path = prompt_path("Enter the path to index.db", must_exist=True, is_dir=False)
    print_success(f"Found database: {db_path}")
    
    # Step 2: Source files
    print_step(2, "Locate your source files directory")
    print("""
This is the directory containing the actual file data, usually:
  /mnt/backupdrive/restsdk/data/files
""")
    source_dir = prompt_path("Enter the path to the source files directory", must_exist=True, is_dir=True)
    print_success(f"Found source directory: {source_dir}")
    
    # Step 3: Destination
    print_step(3, "Choose destination directory")
    print("""
Where do you want to copy your files to? For example:
  /mnt/nfs-media (NFS mount)
  /home/user/recovered (local directory)
""")
    dest_dir = prompt_path("Enter the destination directory path", must_exist=False)
    if not os.path.exists(dest_dir):
        if prompt_yes_no(f"Directory doesn't exist. Create it?", default=True):
            os.makedirs(dest_dir, exist_ok=True)
            print_success(f"Created directory: {dest_dir}")
        else:
            print_error("Cannot continue without destination directory.")
            return 1
    print_success(f"Destination: {dest_dir}")
    
    # Step 4: Farm directory
    print_step(4, "Choose symlink farm directory")
    print("""
The symlink farm is a temporary directory that mirrors your file structure
using symbolic links. It should be on the SAME filesystem as the source.

Recommended: /tmp/restore-farm
""")
    farm_dir = prompt_path("Enter the symlink farm directory path", must_exist=False)
    print_success(f"Farm directory: {farm_dir}")
    
    # Step 5: Options
    print_step(5, "Configure options")
    
    sanitize_pipes = False
    print("""
Some filenames may contain '|' which can cause issues on Windows/NTFS/SMB.
""")
    if prompt_yes_no("Replace '|' with '-' in filenames?", default=False):
        sanitize_pipes = True
        print_success("Will sanitize pipe characters")
    
    use_checksum = prompt_yes_no("Verify files with checksums? (slower but safer)", default=True)
    if use_checksum:
        print_success("Checksum verification enabled")
    else:
        print_warning("Checksum verification disabled - faster but less safe")
    
    dry_run = prompt_yes_no("Do a dry run first (preview only)?", default=True)
    if dry_run:
        print_info("Dry run mode - no files will be copied")
    
    # Step 6: Confirmation
    print_step(6, "Confirm and run")
    print_header("Configuration Summary")
    print(f"  📁 Database:      {db_path}")
    print(f"  📂 Source:        {source_dir}")
    print(f"  💾 Destination:   {dest_dir}")
    print(f"  🔗 Symlink farm:  {farm_dir}")
    print(f"  🔧 Sanitize |:    {'Yes' if sanitize_pipes else 'No'}")
    print(f"  ✅ Checksum:      {'Yes' if use_checksum else 'No'}")
    print(f"  🧪 Dry run:       {'Yes' if dry_run else 'No'}")
    print()
    
    if not prompt_yes_no("Proceed with these settings?", default=True):
        print_info("Wizard cancelled.")
        return 0
    
    # Run restore
    result = run_restore(
        db_path=db_path,
        source=source_dir,
        dest=dest_dir,
        farm=farm_dir,
        checksum=use_checksum,
        dry_run=dry_run,
        retry_count=3,
        log_interval=60,
        log_file='rsync_restore.log',
        sanitize_pipes=sanitize_pipes,
        skip_farm=False,
        limit=0
    )
    
    # Offer to run for real if dry run was successful
    if dry_run and result == 0:
        print()
        if prompt_yes_no("Dry run complete. Would you like to run for real now?", default=True):
            result = run_restore(
                db_path=db_path,
                source=source_dir,
                dest=dest_dir,
                farm=farm_dir,
                checksum=use_checksum,
                dry_run=False,
                retry_count=3,
                log_interval=60,
                log_file='rsync_restore.log',
                sanitize_pipes=sanitize_pipes,
                skip_farm=True  # Farm already exists
            )
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description='rsync-based restore with monitoring and progress tracking',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive wizard (recommended for new users)
  python rsync_restore.py --wizard
  
  # Full restore with defaults
  python rsync_restore.py --db index.db --source /files --dest /nfs --farm /tmp/farm
  
  # Preflight only
  python rsync_restore.py --preflight-only --source /files --dest /nfs
  
  # Dry run (see what would be copied)
  python rsync_restore.py --db index.db --source /files --dest /nfs --farm /tmp/farm --dry-run
  
  # Skip checksum for faster transfer (less safe)
  python rsync_restore.py --db index.db --source /files --dest /nfs --farm /tmp/farm --no-checksum

Cleanup Examples:
  # Interactive cleanup wizard
  python rsync_restore.py --cleanup --db index.db --dest /nfs
  
  # Cleanup with protected folders (dry-run)
  python rsync_restore.py --cleanup --db index.db --dest /nfs \\
      --protect "my-stuff/*" --cleanup-folder "Photos/*" --dry-run
  
  # Cleanup using saved config
  python rsync_restore.py --cleanup --db index.db --dest /nfs --config cleanup_rules.yaml
"""
    )
    
    # Wizard mode
    parser.add_argument('--wizard', '-w', action='store_true',
                       help='Run interactive wizard (recommended for new users)')
    
    # Required arguments (for non-wizard mode)
    parser.add_argument('--db', help='Path to SQLite database (index.db)')
    parser.add_argument('--source', help='Source directory containing files')
    parser.add_argument('--dest', help='Destination directory')
    parser.add_argument('--farm', help='Symlink farm directory')
    
    # Options
    parser.add_argument('--preflight-only', action='store_true',
                       help='Run preflight checks only, do not copy')
    parser.add_argument('--dry-run', '-n', action='store_true',
                       help='Dry run - show what would be copied/deleted')
    parser.add_argument('--no-checksum', action='store_true',
                       help='Skip checksum verification (faster but less safe)')
    parser.add_argument('--retry-count', type=int, default=3,
                       help='Number of retries for failed files (default: 3)')
    parser.add_argument('--log-interval', type=int, default=60,
                       help='Progress log interval in seconds (default: 60)')
    parser.add_argument('--log-file', default='rsync_restore.log',
                       help='Log file path (default: rsync_restore.log)')
    parser.add_argument('--sanitize-pipes', action='store_true',
                       help='Replace | with - in paths')
    parser.add_argument('--skip-farm', action='store_true',
                       help='Skip symlink farm creation (use existing)')
    parser.add_argument('--limit', type=int, default=0,
                       help='Process only first N files (for testing). 0 = no limit (default)')
    
    # Cleanup options
    parser.add_argument('--cleanup', action='store_true',
                       help='Run cleanup mode to find and remove orphan files')
    parser.add_argument('--protect', action='append', default=[],
                       help='Folder pattern to protect from cleanup (can be used multiple times)')
    parser.add_argument('--cleanup-folder', action='append', default=[],
                       help='Folder pattern to cleanup orphans from (can be used multiple times)')
    parser.add_argument('--config', default='cleanup_rules.yaml',
                       help='Path to cleanup config file (default: cleanup_rules.yaml)')
    parser.add_argument('--yes', '-y', action='store_true',
                       help='Auto-confirm deletion (use with caution)')
    
    args = parser.parse_args()
    
    # Wizard mode
    if args.wizard:
        return run_wizard()
    
    # Cleanup mode
    if args.cleanup:
        if not args.db or not args.dest:
            print_error("--cleanup requires --db and --dest")
            return 1
        
        # If wizard flag is also set, run cleanup wizard
        if not args.protect and not args.cleanup_folder and not os.path.exists(args.config):
            # No patterns specified and no config - run wizard
            return run_cleanup_wizard(args.dest, args.db, args.config)
        else:
            # Run CLI cleanup
            return run_cleanup_cli(
                dest_dir=args.dest,
                db_path=args.db,
                config_path=args.config,
                protect_patterns=args.protect,
                cleanup_patterns=args.cleanup_folder,
                dry_run=args.dry_run,
                auto_yes=args.yes
            )
    
    # Preflight only mode
    if args.preflight_only:
        if not args.source or not args.dest:
            print_error("--preflight-only requires --source and --dest")
            return 1
        preflight = run_preflight(args.source, args.dest, args.db, args.farm)
        return 0 if preflight['checks_passed'] else 1
    
    # Full restore - validate required args
    if not args.db or not args.source or not args.dest or not args.farm:
        print_error("Missing required arguments. Need: --db, --source, --dest, --farm")
        parser.print_help()
        return 1
    
    # Run restore
    return run_restore(
        db_path=args.db,
        source=args.source,
        dest=args.dest,
        farm=args.farm,
        checksum=not args.no_checksum,
        dry_run=args.dry_run,
        retry_count=args.retry_count,
        log_interval=args.log_interval,
        log_file=args.log_file,
        sanitize_pipes=args.sanitize_pipes,
        skip_farm=args.skip_farm,
        limit=args.limit
    )


if __name__ == '__main__':
    sys.exit(main())
