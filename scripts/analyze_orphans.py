#!/usr/bin/env python3
"""
Analyze orphan files to understand why they're not matching the database.

This script helps diagnose why files in your destination aren't matching
the MyCloud database, which causes them to be flagged as "orphans" during
cleanup scans.

Common causes this script detects:
1. Filename encoding issues (special characters, unicode problems)
2. Path mismatches (file exists but canonical path differs)
3. Files that exist in dest but not in source
4. Potential duplicates (same filename, different location)

Usage:
    python scripts/analyze_orphans.py --db /path/to/index.db --dest /path/to/dest --folder "OSxData"
    python scripts/analyze_orphans.py -h  # Show full help
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict
import hashlib

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rsync_restore


def get_sample_orphans(dest_dir: str, canonical_paths: set, folder: str, limit: int = 20):
    """Get sample orphan files from a specific folder."""
    orphans = []
    folder_path = Path(dest_dir) / folder
    
    if not folder_path.exists():
        print(f"Folder not found: {folder_path}")
        return []
    
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, dest_dir)
            
            # Check if it's an orphan
            if full_path not in canonical_paths and rel_path not in canonical_paths:
                orphans.append({
                    'path': rel_path,
                    'full_path': full_path,
                    'size': os.path.getsize(full_path) if os.path.exists(full_path) else 0,
                    'name': f
                })
                
                if len(orphans) >= limit:
                    return orphans
    
    return orphans


def find_similar_in_db(db_path: str, filename: str, limit: int = 5):
    """Find files with similar names in the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Try exact match first
    cursor.execute("""
        SELECT f.name, f.id, f.parentID
        FROM Files f
        WHERE f.name = ?
        LIMIT ?
    """, (filename, limit))
    exact = cursor.fetchall()
    
    # Try partial match
    cursor.execute("""
        SELECT f.name, f.id, f.parentID
        FROM Files f
        WHERE f.name LIKE ?
        LIMIT ?
    """, (f"%{filename[:20]}%", limit))
    partial = cursor.fetchall()
    
    conn.close()
    return exact, partial


def analyze_encoding_issues(orphans: list):
    """Check for potential encoding issues in filenames."""
    issues = []
    for orphan in orphans:
        name = orphan['name']
        # Check for common encoding problems
        if '?' in name or '�' in name:
            issues.append((name, "Contains replacement characters"))
        elif any(ord(c) > 127 for c in name):
            issues.append((name, "Contains non-ASCII characters"))
        elif '|' in name:
            issues.append((name, "Contains pipe character (may need sanitization)"))
    return issues


def check_source_existence(source_dir: str, orphans: list):
    """Check if orphan files exist in the source directory."""
    results = []
    for orphan in orphans[:10]:  # Limit to avoid long waits
        # Try to find in source
        rel_path = orphan['path']
        source_path = os.path.join(source_dir, rel_path)
        exists = os.path.exists(source_path)
        results.append({
            'path': rel_path,
            'in_source': exists,
            'source_path': source_path
        })
    return results


def main():
    parser = argparse.ArgumentParser(
        description='Analyze orphan files to understand why they don\'t match the database.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze orphans in OSxData folder
  python scripts/analyze_orphans.py \\
    --db /mnt/backupdrive/restsdk/data/db/index.db \\
    --dest /mnt/nfs-media/ \\
    --folder "OSxData"

  # Include source check to see if files exist in source
  python scripts/analyze_orphans.py \\
    --db /mnt/backupdrive/restsdk/data/db/index.db \\
    --dest /mnt/nfs-media/ \\
    --source /mnt/backupdrive/restsdk/data/files/ \\
    --folder "iOSBackup" \\
    --limit 50

Common causes of orphans:
  1. Filename encoding issues (special chars, unicode)
  2. Path mismatches (file exists but path differs from DB)
  3. Files copied by legacy script with different naming
  4. Duplicates (same file, different location)
"""
    )
    parser.add_argument('--db', required=True, 
                        help='Path to MyCloud index.db database')
    parser.add_argument('--dest', required=True, 
                        help='Destination directory to scan for orphans')
    parser.add_argument('--source', 
                        help='Source directory (optional, checks if orphans exist in source)')
    parser.add_argument('--folder', required=True, 
                        help='Specific folder within dest to analyze')
    parser.add_argument('--limit', type=int, default=20, 
                        help='Number of sample orphans to analyze (default: 20)')
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"  Orphan Analysis: {args.folder}")
    print(f"{'='*60}\n")
    
    # Load canonical paths
    print("Loading canonical paths from database...")
    canonical_paths = rsync_restore.get_canonical_paths_from_db(args.db)
    print(f"  Loaded {len(canonical_paths):,} canonical paths\n")
    
    # Get sample orphans
    print(f"Sampling orphan files from {args.folder}...")
    orphans = get_sample_orphans(args.dest, canonical_paths, args.folder, args.limit)
    print(f"  Found {len(orphans)} sample orphans\n")
    
    if not orphans:
        print("No orphans found in this folder.")
        return
    
    # Display samples
    print("Sample orphan files:")
    print("-" * 60)
    for i, orphan in enumerate(orphans[:10], 1):
        size_kb = orphan['size'] / 1024
        print(f"  {i}. {orphan['path']}")
        print(f"     Size: {size_kb:.1f} KB")
    print()
    
    # Check for encoding issues
    print("Checking for encoding issues...")
    encoding_issues = analyze_encoding_issues(orphans)
    if encoding_issues:
        print(f"  Found {len(encoding_issues)} files with potential encoding issues:")
        for name, issue in encoding_issues[:5]:
            print(f"    - {name}: {issue}")
    else:
        print("  No obvious encoding issues found.")
    print()
    
    # Look for similar files in DB
    print("Searching for similar files in database...")
    for orphan in orphans[:5]:
        exact, partial = find_similar_in_db(args.db, orphan['name'])
        if exact:
            print(f"  '{orphan['name']}' - EXACT MATCH in DB ({len(exact)} found)")
            print(f"    → Path mismatch likely (file exists but in different location)")
        elif partial:
            print(f"  '{orphan['name']}' - Similar names found: {len(partial)}")
        else:
            print(f"  '{orphan['name']}' - No match in DB")
    print()
    
    # Check source existence if provided
    if args.source:
        print("Checking if orphans exist in source...")
        source_results = check_source_existence(args.source, orphans)
        in_source = sum(1 for r in source_results if r['in_source'])
        print(f"  {in_source}/{len(source_results)} orphans exist in source")
        if in_source > 0:
            print("  → These files may have path reconstruction issues")
    
    print()
    print("=" * 60)
    print("  Recommendations")
    print("=" * 60)
    print()
    
    if encoding_issues:
        print("• Some files have encoding issues - consider running with --sanitize-pipes")
    
    print("• Review the sample files above to understand the pattern")
    print("• If files are duplicates or old backups, consider adding to cleanup list")
    print("• If files should be kept, add folder to protect list")
    print()


if __name__ == '__main__':
    main()
