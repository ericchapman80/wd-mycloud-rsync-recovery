#!/usr/bin/env python3
"""
Diagnose path reconstruction issues by comparing canonical paths from the
database against what actually exists in the source directory.

This script helps identify why symlink farm creation might be failing to
find source files, which is critical for understanding the 
"1,655,945 errors" issue.

Usage:
    python scripts/diagnose_paths.py --db /path/to/index.db --source /path/to/source
    python scripts/diagnose_paths.py -h  # Show full help
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rsync_restore


def get_db_file_count(db_path: str) -> int:
    """Get total file count from database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM Files WHERE contentID IS NOT NULL")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def sample_canonical_paths(db_path: str, limit: int = 100) -> list:
    """Get a sample of canonical paths from the database."""
    canonical_paths = rsync_restore.get_canonical_paths_from_db(db_path)
    return list(canonical_paths)[:limit]


def check_path_existence(source_dir: str, paths: list) -> dict:
    """Check which canonical paths actually exist in source."""
    results = {
        'found': [],
        'not_found': [],
        'partial_match': []
    }
    
    for path in paths:
        full_path = os.path.join(source_dir, path)
        if os.path.exists(full_path):
            results['found'].append(path)
        else:
            # Try to find partial matches
            parts = path.split('/')
            partial_found = False
            for i in range(len(parts), 0, -1):
                partial = '/'.join(parts[:i])
                partial_path = os.path.join(source_dir, partial)
                if os.path.exists(partial_path):
                    results['partial_match'].append({
                        'canonical': path,
                        'exists_up_to': partial,
                        'missing_from': '/'.join(parts[i:]) if i < len(parts) else ''
                    })
                    partial_found = True
                    break
            
            if not partial_found:
                results['not_found'].append(path)
    
    return results


def analyze_source_structure(source_dir: str, max_depth: int = 2) -> dict:
    """Analyze the actual structure of the source directory."""
    structure = {
        'top_level_dirs': [],
        'top_level_files': [],
        'sample_paths': []
    }
    
    source_path = Path(source_dir)
    
    # Get top-level items
    try:
        for item in source_path.iterdir():
            if item.is_dir():
                structure['top_level_dirs'].append(item.name)
            else:
                structure['top_level_files'].append(item.name)
    except PermissionError:
        structure['error'] = "Permission denied reading source directory"
        return structure
    
    # Get sample of actual file paths
    count = 0
    for root, dirs, files in os.walk(source_dir):
        for f in files:
            if count >= 20:
                break
            rel_path = os.path.relpath(os.path.join(root, f), source_dir)
            structure['sample_paths'].append(rel_path)
            count += 1
        if count >= 20:
            break
    
    return structure


def compare_path_formats(db_paths: list, source_paths: list) -> dict:
    """Compare path formats between DB and source to find patterns."""
    analysis = {
        'db_path_patterns': defaultdict(int),
        'source_path_patterns': defaultdict(int),
        'common_prefixes_db': defaultdict(int),
        'common_prefixes_source': defaultdict(int)
    }
    
    for path in db_paths[:100]:
        parts = path.split('/')
        if parts:
            analysis['common_prefixes_db'][parts[0]] += 1
        # Check for contentID-style paths
        if len(parts) >= 2 and len(parts[0]) == 2:
            analysis['db_path_patterns']['contentID_style'] += 1
        else:
            analysis['db_path_patterns']['folder_style'] += 1
    
    for path in source_paths[:100]:
        parts = path.split('/')
        if parts:
            analysis['common_prefixes_source'][parts[0]] += 1
    
    return analysis


def main():
    parser = argparse.ArgumentParser(
        description='Diagnose path reconstruction issues between DB and source.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic diagnosis
  python scripts/diagnose_paths.py \\
    --db /mnt/backupdrive/restsdk/data/db/index.db \\
    --source /mnt/backupdrive/restsdk/data/files/

  # With more samples
  python scripts/diagnose_paths.py \\
    --db /mnt/backupdrive/restsdk/data/db/index.db \\
    --source /mnt/backupdrive/restsdk/data/files/ \\
    --samples 200

This script helps diagnose why symlink farm creation fails to find files.
Common issues:
  1. Path reconstruction doesn't match actual source structure
  2. ContentID-based paths vs folder-based paths mismatch
  3. Encoding differences between DB and filesystem
"""
    )
    parser.add_argument('--db', required=True,
                        help='Path to MyCloud index.db database')
    parser.add_argument('--source', required=True,
                        help='Source directory containing actual files')
    parser.add_argument('--samples', type=int, default=100,
                        help='Number of paths to sample (default: 100)')
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"  Path Reconstruction Diagnosis")
    print(f"{'='*60}\n")
    
    # Check database
    print("Checking database...")
    db_file_count = get_db_file_count(args.db)
    print(f"  Files in database: {db_file_count:,}")
    
    # Get canonical paths
    print(f"\nSampling {args.samples} canonical paths from database...")
    canonical_paths = sample_canonical_paths(args.db, args.samples)
    print(f"  Got {len(canonical_paths)} sample paths")
    
    # Show sample canonical paths
    print("\nSample canonical paths from DB:")
    print("-" * 60)
    for path in canonical_paths[:10]:
        print(f"  {path}")
    print()
    
    # Analyze source structure
    print("Analyzing source directory structure...")
    source_structure = analyze_source_structure(args.source)
    
    if 'error' in source_structure:
        print(f"  ERROR: {source_structure['error']}")
        return 1
    
    print(f"  Top-level directories: {len(source_structure['top_level_dirs'])}")
    print(f"  Top-level files: {len(source_structure['top_level_files'])}")
    
    print("\nTop-level directories in source:")
    for d in sorted(source_structure['top_level_dirs'])[:15]:
        print(f"  📁 {d}/")
    if len(source_structure['top_level_dirs']) > 15:
        print(f"  ... and {len(source_structure['top_level_dirs']) - 15} more")
    
    print("\nSample actual file paths in source:")
    print("-" * 60)
    for path in source_structure['sample_paths'][:10]:
        print(f"  {path}")
    print()
    
    # Check path existence
    print(f"Checking if canonical paths exist in source...")
    existence_results = check_path_existence(args.source, canonical_paths)
    
    found = len(existence_results['found'])
    not_found = len(existence_results['not_found'])
    partial = len(existence_results['partial_match'])
    
    print(f"\n  ✅ Found: {found}/{len(canonical_paths)} ({100*found/len(canonical_paths):.1f}%)")
    print(f"  ❌ Not found: {not_found}/{len(canonical_paths)} ({100*not_found/len(canonical_paths):.1f}%)")
    print(f"  ⚠️  Partial match: {partial}/{len(canonical_paths)} ({100*partial/len(canonical_paths):.1f}%)")
    
    # Show partial matches (most informative)
    if existence_results['partial_match']:
        print("\nPartial matches (path exists up to a point):")
        print("-" * 60)
        for pm in existence_results['partial_match'][:5]:
            print(f"  Canonical: {pm['canonical']}")
            print(f"  Exists:    {pm['exists_up_to']}/")
            print(f"  Missing:   {pm['missing_from']}")
            print()
    
    # Show not found examples
    if existence_results['not_found']:
        print("\nPaths not found at all:")
        print("-" * 60)
        for path in existence_results['not_found'][:5]:
            print(f"  {path}")
    
    # Compare path formats
    print("\n" + "=" * 60)
    print("  Analysis")
    print("=" * 60)
    
    comparison = compare_path_formats(canonical_paths, source_structure['sample_paths'])
    
    print("\nDB path prefixes (first folder):")
    for prefix, count in sorted(comparison['common_prefixes_db'].items(), key=lambda x: -x[1])[:10]:
        print(f"  {prefix}: {count}")
    
    print("\nSource path prefixes (first folder):")
    for prefix, count in sorted(comparison['common_prefixes_source'].items(), key=lambda x: -x[1])[:10]:
        print(f"  {prefix}: {count}")
    
    print("\nDB path patterns:")
    for pattern, count in comparison['db_path_patterns'].items():
        print(f"  {pattern}: {count}")
    
    # Recommendations
    print("\n" + "=" * 60)
    print("  Recommendations")
    print("=" * 60)
    print()
    
    if found == 0:
        print("⚠️  CRITICAL: No canonical paths found in source!")
        print("   This suggests a fundamental path reconstruction mismatch.")
        print("   The DB paths don't match the actual source file structure.")
        print()
        print("   Possible causes:")
        print("   - Source directory is wrong")
        print("   - Path reconstruction algorithm needs adjustment")
        print("   - Files are stored with contentID names, not folder paths")
    elif found < len(canonical_paths) * 0.5:
        print("⚠️  WARNING: Less than 50% of paths found in source.")
        print("   Path reconstruction may have issues with certain path types.")
    else:
        print("✅ Path reconstruction appears to be working for most files.")
    
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
