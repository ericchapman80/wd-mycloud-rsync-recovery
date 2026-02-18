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
    parser.add_argument('--deep', action='store_true', help='Deep analysis of all files')
    
    args = parser.parse_args()
    
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    if args.deep:
        # Deep analysis - check ALL files and categorize failures
        print(f"\n{'='*70}")
        print(f"  Deep ContentID Analysis - Checking ALL files")
        print(f"{'='*70}\n")
        
        cur.execute("SELECT COUNT(*) FROM files WHERE contentID IS NOT NULL AND contentID != ''")
        total = cur.fetchone()[0]
        print(f"Total files with contentID: {total:,}")
        
        cur.execute("""
            SELECT id, name, parentID, contentID 
            FROM files 
            WHERE contentID IS NOT NULL AND contentID != ''
        """)
        
        found = 0
        not_found = 0
        is_directory = 0
        empty_contentid = 0
        sample_not_found = []
        sample_is_dir = []
        
        for row in cur:
            content_id = row['contentID']
            
            if not content_id or content_id.strip() == '':
                empty_contentid += 1
                continue
            
            # Try to find the file
            candidates = [
                os.path.join(args.source, content_id[0], content_id),
                os.path.join(args.source, content_id),
            ]
            
            found_path = None
            for c in candidates:
                if os.path.exists(c):
                    found_path = c
                    break
            
            if found_path:
                if os.path.isdir(found_path):
                    is_directory += 1
                    if len(sample_is_dir) < 5:
                        sample_is_dir.append((row['name'], content_id, found_path))
                else:
                    found += 1
            else:
                not_found += 1
                if len(sample_not_found) < 10:
                    sample_not_found.append((row['name'], content_id, candidates[0]))
        
        print(f"\nResults:")
        print(f"  ✅ Found (files):     {found:,} ({100*found/total:.1f}%)")
        print(f"  📁 Found (dirs):      {is_directory:,} ({100*is_directory/total:.1f}%)")
        print(f"  ❌ Not found:         {not_found:,} ({100*not_found/total:.1f}%)")
        print(f"  ⚠️  Empty contentID:  {empty_contentid:,}")
        
        if sample_not_found:
            print(f"\nSample NOT FOUND files:")
            print("-" * 70)
            for name, cid, path in sample_not_found:
                print(f"  Name: {name}")
                print(f"  contentID: {cid}")
                print(f"  Expected: {path}")
                print()
        
        if sample_is_dir:
            print(f"\nSample DIRECTORY entries (contentID points to dir):")
            print("-" * 70)
            for name, cid, path in sample_is_dir:
                print(f"  Name: {name}")
                print(f"  contentID: {cid}")
                print(f"  Path: {path}")
                print()
        
        return
    
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
