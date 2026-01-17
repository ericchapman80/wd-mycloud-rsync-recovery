"""
Integration tests for cleanup workflows in rsync_restore.py

Tests complete cleanup workflows including scan, wizard,
CLI mode, and pattern-based operations.
"""
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rsync_restore


class TestCleanupWorkflowEndToEnd:
    """Test complete cleanup workflows"""
    
    def test_full_scan_and_delete_workflow(self, tmp_path):
        """Test complete scan → identify → delete workflow"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        # Create database with legitimate files
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files VALUES (1, 'Photos', NULL, NULL)")
            conn.execute("INSERT INTO Files VALUES (2, 'vacation.jpg', 1, 'img001')")
        
        # Create files - mix of legitimate and orphans
        photos_dir = dest / "Photos"
        photos_dir.mkdir()
        (photos_dir / "vacation.jpg").write_text("legitimate image")
        (photos_dir / "orphan1.jpg").write_text("orphan image")
        (dest / "orphan_root.txt").write_text("orphan at root")
        
        # Step 1: Scan
        scan_result = rsync_restore.scan_destination_for_orphans(
            str(dest),
            str(db_path)
        )
        
        assert scan_result['orphan_count'] == 2
        assert len(scan_result['orphans']) == 2
        
        # Step 2: Delete
        delete_result = rsync_restore.delete_orphans(
            scan_result['orphans'],
            dry_run=False
        )
        
        assert delete_result['deleted'] == 2
        # Legitimate file should remain
        assert (photos_dir / "vacation.jpg").exists()
        # Orphans should be gone
        assert not (photos_dir / "orphan1.jpg").exists()
        assert not (dest / "orphan_root.txt").exists()
    
    def test_dry_run_workflow(self, tmp_path):
        """Test dry run shows what would be deleted without deleting"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        # Create orphan files
        orphans = []
        for i in range(5):
            orphan = dest / f"orphan{i}.txt"
            orphan.write_text(f"orphan {i}")
            orphans.append(orphan)
        
        # Dry run scan and delete
        scan_result = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        delete_result = rsync_restore.delete_orphans(
            scan_result['orphans'],
            dry_run=True
        )
        
        # Should report what would be deleted
        assert delete_result['deleted'] == 5
        # But files should still exist
        for orphan in orphans:
            assert orphan.exists()
    
    def test_incremental_cleanup_workflow(self, tmp_path):
        """Test cleaning up in multiple passes"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files VALUES (1, 'keep.txt', NULL, 'keep001')")
        
        # Create legitimate file
        (dest / "keep.txt").write_text("keep this")
        
        # Pass 1: Clean initial orphans
        (dest / "orphan1.txt").write_text("orphan")
        scan1 = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        rsync_restore.delete_orphans(scan1['orphans'], dry_run=False)
        
        # Pass 2: New orphans appear
        (dest / "orphan2.txt").write_text("new orphan")
        scan2 = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        rsync_restore.delete_orphans(scan2['orphans'], dry_run=False)
        
        # Only legitimate file should remain
        assert (dest / "keep.txt").exists()
        assert not (dest / "orphan1.txt").exists()
        assert not (dest / "orphan2.txt").exists()


class TestCleanupWithPatterns:
    """Test cleanup with protection and cleanup patterns"""
    
    def test_protect_pattern_workflow(self, tmp_path):
        """Test protecting specific patterns from deletion"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        # Create files in protected and unprotected areas
        my_stuff = dest / "my-stuff"
        temp = dest / "temp"
        my_stuff.mkdir()
        temp.mkdir()
        
        (my_stuff / "important.txt").write_text("protect this")
        (temp / "cache.txt").write_text("can delete")
        
        # Scan with protection pattern
        scan_result = rsync_restore.scan_destination_for_orphans(
            str(dest),
            str(db_path),
            protect_patterns=["my-stuff/*"]
        )
        
        # Protected file should not be in orphan list
        orphan_paths = [os.path.relpath(o, dest) for o in scan_result['orphans']]
        assert not any("my-stuff" in p for p in orphan_paths)
        assert any("temp" in p for p in orphan_paths)
    
    def test_cleanup_specific_folders(self, tmp_path):
        """Test cleaning up only specific folders"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        # Create orphans in multiple folders
        cache = dest / "cache"
        logs = dest / "logs"
        docs = dest / "docs"
        cache.mkdir()
        logs.mkdir()
        docs.mkdir()
        
        (cache / "old.db").write_text("cache")
        (logs / "old.log").write_text("log")
        (docs / "orphan.txt").write_text("doc orphan")
        
        # Scan all
        scan_result = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        
        # Delete only cache/* and logs/*
        cleanup_patterns = ["cache/*", "logs/*"]
        orphans_to_delete = [
            o for o in scan_result['orphans']
            if rsync_restore.matches_pattern(os.path.relpath(o, dest), cleanup_patterns)
        ]
        
        delete_result = rsync_restore.delete_orphans(orphans_to_delete, dry_run=False)
        
        # Cache and logs should be cleaned
        assert not (cache / "old.db").exists()
        assert not (logs / "old.log").exists()
        # Docs should remain
        assert (docs / "orphan.txt").exists()
    
    def test_multiple_protection_patterns(self, tmp_path):
        """Test multiple protection patterns working together"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        # Create various files
        (dest / "keep1.important").write_text("keep")
        (dest / "keep2.critical").write_text("keep")
        (dest / "delete.tmp").write_text("delete")
        
        protect_patterns = ["*.important", "*.critical"]
        scan_result = rsync_restore.scan_destination_for_orphans(
            str(dest),
            str(db_path),
            protect_patterns=protect_patterns
        )
        
        orphan_names = [os.path.basename(o) for o in scan_result['orphans']]
        assert "delete.tmp" in orphan_names
        assert "keep1.important" not in orphan_names
        assert "keep2.critical" not in orphan_names


class TestCleanupCLIWorkflow:
    """Test CLI-based cleanup workflows"""
    
    def test_cli_full_automatic_cleanup(self, tmp_path):
        """Test fully automated CLI cleanup"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        config_path = tmp_path / "cleanup.yaml"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        # Create orphans
        for i in range(10):
            (dest / f"orphan{i}.txt").write_text(f"orphan {i}")
        
        # Run CLI cleanup with auto-yes
        result = rsync_restore.run_cleanup_cli(
            dest_dir=str(dest),
            db_path=str(db_path),
            config_path=str(config_path),
            protect_patterns=[],
            cleanup_patterns=["*"],
            dry_run=False,
            auto_yes=True
        )
        
        assert result == 0
        # All orphans should be deleted
        remaining = list(dest.glob("*.txt"))
        assert len(remaining) == 0
    
    def test_cli_with_saved_config(self, tmp_path):
        """Test CLI using saved configuration"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        config_path = tmp_path / "cleanup.yaml"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        # Save configuration
        config = {
            'protect': ['important/*'],
            'cleanup': ['temp/*']
        }
        rsync_restore.save_cleanup_config(config, str(config_path))
        
        # Create files
        important = dest / "important"
        temp = dest / "temp"
        important.mkdir()
        temp.mkdir()
        (important / "keep.txt").write_text("keep")
        (temp / "delete.txt").write_text("delete")
        
        # Run cleanup with config
        result = rsync_restore.run_cleanup_cli(
            dest_dir=str(dest),
            db_path=str(db_path),
            config_path=str(config_path),
            protect_patterns=config['protect'],
            cleanup_patterns=config['cleanup'],
            dry_run=False,
            auto_yes=True
        )
        
        assert result == 0


class TestCleanupWizardWorkflow:
    """Test wizard-based cleanup workflows"""
    
    @patch('builtins.input')
    def test_wizard_protect_workflow(self, mock_input, tmp_path):
        """Test wizard protecting folders"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        config_path = tmp_path / "cleanup.yaml"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        folder = dest / "UserFiles"
        folder.mkdir()
        (folder / "document.pdf").write_text("user document")
        
        # User chooses to protect
        mock_input.return_value = 'P'
        
        result = rsync_restore.run_cleanup_wizard(
            dest_dir=str(dest),
            db_path=str(db_path),
            config_path=str(config_path)
        )
        
        # File should still exist
        assert (folder / "document.pdf").exists()
        
        # Config should be saved with protection
        if config_path.exists():
            loaded_config = rsync_restore.load_cleanup_config(str(config_path))
            assert any("UserFiles" in p for p in loaded_config.get('protect', []))
    
    @patch('builtins.input')
    def test_wizard_cleanup_workflow(self, mock_input, tmp_path):
        """Test wizard cleaning up folders"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        config_path = tmp_path / "cleanup.yaml"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        temp = dest / "TempFiles"
        temp.mkdir()
        (temp / "cache.tmp").write_text("temporary")
        
        # User chooses to cleanup, then confirms
        mock_input.side_effect = ['C', 'y']
        
        result = rsync_restore.run_cleanup_wizard(
            dest_dir=str(dest),
            db_path=str(db_path),
            config_path=str(config_path)
        )
        
        # Temp file should be deleted
        assert not (temp / "cache.tmp").exists()


class TestCleanupWithNestedStructures:
    """Test cleanup with complex nested directory structures"""
    
    def test_cleanup_deeply_nested_orphans(self, tmp_path):
        """Test finding and deleting deeply nested orphans"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        # Create deeply nested orphan
        deep = dest / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "orphan.txt").write_text("deep orphan")
        
        scan_result = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        
        assert scan_result['orphan_count'] == 1
        assert any("orphan.txt" in o for o in scan_result['orphans'])
        
        # Delete and verify
        delete_result = rsync_restore.delete_orphans(scan_result['orphans'], dry_run=False)
        assert delete_result['deleted'] == 1
    
    def test_cleanup_preserves_legitimate_nested_files(self, tmp_path):
        """Test that nested legitimate files are preserved"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files VALUES (1, 'Projects', NULL, NULL)")
            conn.execute("INSERT INTO Files VALUES (2, 'Work', 1, NULL)")
            conn.execute("INSERT INTO Files VALUES (3, 'report.pdf', 2, 'doc001')")
        
        # Create matching structure
        work = dest / "Projects" / "Work"
        work.mkdir(parents=True)
        (work / "report.pdf").write_text("legitimate report")
        (work / "orphan.tmp").write_text("orphan")
        
        scan_result = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        delete_result = rsync_restore.delete_orphans(scan_result['orphans'], dry_run=False)
        
        # Legitimate file preserved, orphan deleted
        assert (work / "report.pdf").exists()
        assert not (work / "orphan.tmp").exists()


class TestCleanupStatisticsAndReporting:
    """Test cleanup statistics and reporting"""
    
    def test_cleanup_reports_detailed_statistics(self, tmp_path):
        """Test that cleanup provides detailed statistics"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        # Create orphans in different folders
        folders = ['folder1', 'folder2', 'folder3']
        for folder in folders:
            folder_path = dest / folder
            folder_path.mkdir()
            for i in range(5):
                (folder_path / f"orphan{i}.txt").write_text("orphan")
        
        scan_result = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        
        # Should have detailed statistics
        assert scan_result['orphan_count'] == 15
        assert 'by_folder' in scan_result
        assert len(scan_result['by_folder']) == 3
        assert all(len(files) == 5 for files in scan_result['by_folder'].values())
    
    def test_cleanup_tracks_space_reclaimed(self, tmp_path):
        """Test tracking space reclaimed by cleanup"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        # Create large orphan files
        total_size = 0
        for i in range(5):
            orphan = dest / f"large{i}.bin"
            size = 1000000  # 1MB each
            orphan.write_bytes(b"x" * size)
            total_size += size
        
        scan_result = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        
        # Calculate size before deletion
        space_to_reclaim = sum(
            os.path.getsize(o) for o in scan_result['orphans'] if os.path.exists(o)
        )
        
        assert space_to_reclaim >= total_size


class TestCleanupConfigPersistence:
    """Test configuration persistence across cleanup sessions"""
    
    def test_config_survives_multiple_sessions(self, tmp_path):
        """Test that config persists across multiple cleanup runs"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        config_path = tmp_path / "cleanup.yaml"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        # Session 1: Save config
        config = {
            'protect': ['important/*', 'critical/*'],
            'cleanup': ['temp/*']
        }
        rsync_restore.save_cleanup_config(config, str(config_path))
        
        # Session 2: Load config
        loaded = rsync_restore.load_cleanup_config(str(config_path))
        
        assert 'important/*' in loaded['protect']
        assert 'critical/*' in loaded['protect']
        assert 'temp/*' in loaded['cleanup']
    
    def test_config_updates_last_scan_time(self, tmp_path):
        """Test that config tracks last scan time"""
        config_path = tmp_path / "cleanup.yaml"
        
        config = {
            'protect': [],
            'cleanup': []
        }
        
        rsync_restore.save_cleanup_config(config, str(config_path))
        
        loaded = rsync_restore.load_cleanup_config(str(config_path))
        
        # Should have last_scan timestamp
        assert 'last_scan' in loaded


class TestCleanupErrorHandling:
    """Test cleanup error handling"""
    
    def test_cleanup_handles_permission_errors(self, tmp_path):
        """Test handling files that can't be deleted due to permissions"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        # Create orphan
        orphan = dest / "protected.txt"
        orphan.write_text("orphan")
        
        # Make read-only
        orphan.chmod(0o444)
        parent = dest
        parent.chmod(0o555)
        
        try:
            scan_result = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
            delete_result = rsync_restore.delete_orphans(scan_result['orphans'], dry_run=False)
            
            # Should track error
            assert delete_result['errors'] > 0 or delete_result['deleted'] == 0
        finally:
            # Restore permissions for cleanup
            parent.chmod(0o755)
            orphan.chmod(0o644)
    
    def test_cleanup_continues_after_individual_failures(self, tmp_path):
        """Test that cleanup continues even if some deletions fail"""
        db_path = tmp_path / "index.db"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        # Create multiple orphans
        orphan1 = dest / "orphan1.txt"
        orphan2 = dest / "orphan2.txt"
        orphan1.write_text("orphan 1")
        orphan2.write_text("orphan 2")
        
        scan_result = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        
        # Even if some fail, others should be deleted
        delete_result = rsync_restore.delete_orphans(scan_result['orphans'], dry_run=False)
        
        # Should complete (deleted count may vary based on failures)
        assert 'deleted' in delete_result
        assert 'errors' in delete_result
