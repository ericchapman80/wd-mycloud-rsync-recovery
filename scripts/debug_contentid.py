#!/usr/bin/env python3
"""Debug script to check contentID values and source file existence."""

import argparse
import os
import sqlite3
import sys

def main():
    parser = argparse.ArgumentParser(description='Debug contentID values')
    parser.add_argument('--db', required=True, help='Path to index.db')
    parser.add_argument('--source', required=True, help='Source directory')
    parser.add_argument('--limit', type=int, default=20, help='Number of samples')
    
    args = parser.parse_args()
    
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Get sample contentIDs
    cur.execute("""
        SELECT id, name, parentID, contentID 
        FROM files 
        WHERE contentID IS NOT NULL AND contentID != ''
        LIMIT ?
    """, (args.limit,))
    
    print(f"\n{'='*70}")
    print(f"  ContentID Debug - Checking {args.limit} samples")
    print(f"{'='*70}\n")
    
    found = 0
    not_found = 0
    
    for row in cur:
        content_id = row['contentID']
        name = row['name']
        
        # Try different path patterns
        candidates = [
            os.path.join(args.source, content_id[0], content_id) if content_id else None,
            os.path.join(args.source, content_id) if content_id else None,
            os.path.join(args.source, content_id[0].lower(), content_id) if content_id else None,
        ]
        
        found_path = None
        for c in candidates:
            if c and os.path.exists(c):
                found_path = c
                break
        
        status = "✅ FOUND" if found_path else "❌ NOT FOUND"
        if found_path:
            found += 1
        else:
            not_found += 1
        
        print(f"File: {name}")
        print(f"  contentID: '{content_id}'")
        print(f"  contentID[0]: '{content_id[0] if content_id else 'N/A'}'")
        print(f"  Expected path: {candidates[0]}")
        print(f"  Status: {status}")
        if found_path:
            print(f"  Found at: {found_path}")
        print()
    
    print(f"{'='*70}")
    print(f"  Summary: {found} found, {not_found} not found")
    print(f"{'='*70}\n")
    
    # Also check what's actually in the source directory
    print("Sample files in source directory:")
    print("-" * 70)
    count = 0
    for root, dirs, files in os.walk(args.source):
        for f in files[:5]:
            rel = os.path.relpath(os.path.join(root, f), args.source)
            print(f"  {rel}")
            count += 1
        if count >= 10:
            break
    
    conn.close()

if __name__ == '__main__':
    main()
