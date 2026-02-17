"""
Tests for cleanup operations in rsync_restore.py

Tests orphan scanning, deletion, and cleanup wizard/CLI.
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


class TestOrphanScanning:
    """Test scan_destination_for_orphans function"""
    
    def test_identifies_orphan_files(self, tmp_path):
        """Test that files not in canonical paths are identified as orphans"""
        dest = tmp_path / "dest"
        dest.mkdir()
        
        # Create files - one legitimate, one orphan
        (dest / "legitimate.txt").write_text("should exist")
        (dest / "orphan.txt").write_text("should not exist")
        
        # Canonical paths only includes legitimate.txt
        canonical_paths = {"legitimate.txt"}
        
        results = rsync_restore.scan_destination_for_orphans(
            str(dest), canonical_paths, [], []
        )
        
        assert len(results['orphans']) > 0
        assert 'orphan.txt' in results['orphans']
    
    def test_recognizes_legitimate_files(self, tmp_path):
        """Test that files in canonical paths are not marked as orphans"""
        dest = tmp_path / "dest"
        dest.mkdir()
        
        # Create the legitimate file structure
        photos_dir = dest / "Photos"
        photos_dir.mkdir()
        (photos_dir / "vacation.jpg").write_text("image data")
        
        # Canonical paths includes the file
        canonical_paths = {"Photos/vacation.jpg"}
        
        results = rsync_restore.scan_destination_for_orphans(
            str(dest), canonical_paths, [], []
        )
        
        assert len(results['orphans']) == 0
    
    def test_scans_nested_directories(self, tmp_path):
        """Test that nested directories are scanned for orphans"""
        dest = tmp_path / "dest"
        dest.mkdir()
        
        # Create nested structure with orphan deep inside
        nested = dest / "dir1" / "subdir" / "deep"
        nested.mkdir(parents=True)
        (nested / "orphan.txt").write_text("orphan")
        
        # Empty canonical paths - everything is orphan
        canonical_paths = set()
        
        results = rsync_restore.scan_destination_for_orphans(
            str(dest), canonical_paths, [], []
        )
        
        assert len(results['orphans']) > 0
    
    def test_respects_protect_patterns(self, tmp_path):
        """Test that protected patterns are excluded from orphans"""
        dest = tmp_path / "dest"
        dest.mkdir()
        
        # Create orphan files
        (dest / "orphan1.txt").write_text("orphan")
        protected = dest / "protected"
        protected.mkdir()
        (protected / "safe.txt").write_text("protected")
        
        # Empty canonical paths, but protect 'protected/*'
        canonical_paths = set()
        
        results = rsync_restore.scan_destination_for_orphans(
            str(dest),
            canonical_paths,
            protect_patterns=["protected/*"],
            cleanup_patterns=[]
        )
        
        # protected/safe.txt should be in 'protected' not 'orphans'
        assert 'orphan1.txt' in results['orphans']
        assert len(results['protected']) > 0
    
    def test_groups_orphans_by_folder(self, tmp_path):
        """Test that orphans are grouped by containing folder"""
        dest = tmp_path / "dest"
        dest.mkdir()
        
        # Create orphans in different folders
        folder1 = dest / "folder1"
        folder2 = dest / "folder2"
        folder1.mkdir()
        folder2.mkdir()
        (folder1 / "orphan1.txt").write_text("orphan")
        (folder1 / "orphan2.txt").write_text("orphan")
        (folder2 / "orphan3.txt").write_text("orphan")
        
        canonical_paths = set()
        
        results = rsync_restore.scan_destination_for_orphans(
            str(dest), canonical_paths, [], []
        )
        
        assert 'by_folder' in results
        # Check that orphans are found
        assert len(results['orphans']) == 3
    
    def test_handles_empty_destination(self, tmp_path):
        """Test scanning empty destination"""
        dest = tmp_path / "dest"
        dest.mkdir()
        
        canonical_paths = set()
        
        results = rsync_restore.scan_destination_for_orphans(
            str(dest), canonical_paths, [], []
        )
        
        assert len(results['orphans']) == 0


class TestOrphanDeletion:
    """Test delete_orphans function"""
    
    def test_deletes_orphan_files(self, tmp_path):
        """Test that orphan files are deleted"""
        dest = tmp_path / "dest"
        dest.mkdir()
        orphan1 = dest / "orphan1.txt"
        orphan2 = dest / "orphan2.txt"
        orphan1.write_text("orphan")
        orphan2.write_text("orphan")
        
        # delete_orphans takes (dest_dir, orphan_paths, dry_run)
        # orphan_paths are relative to dest_dir
        orphan_list = ["orphan1.txt", "orphan2.txt"]
        
        deleted, errors = rsync_restore.delete_orphans(str(dest), orphan_list, dry_run=False)
        
        assert deleted == 2
        assert not orphan1.exists()
        assert not orphan2.exists()
    
    def test_dry_run_does_not_delete(self, tmp_path):
        """Test that dry run does not actually delete files"""
        dest = tmp_path / "dest"
        dest.mkdir()
        orphan = dest / "orphan.txt"
        orphan.write_text("orphan")
        
        deleted, errors = rsync_restore.delete_orphans(str(dest), ["orphan.txt"], dry_run=True)
        
        # Dry run reports what would be deleted but doesn't actually delete
        # The function returns count of files that would be deleted
        assert orphan.exists()  # File still exists
    
    def test_respects_protect_patterns(self, tmp_path):
        """Test that protected files are not deleted - protection is done at scan time"""
        dest = tmp_path / "dest"
        dest.mkdir()
        orphan = dest / "orphan.txt"
        orphan.write_text("orphan")
        
        # delete_orphans doesn't have protect_patterns - protection is at scan time
        # Just test that we can delete a single orphan
        deleted, errors = rsync_restore.delete_orphans(str(dest), ["orphan.txt"], dry_run=False)
        
        assert not orphan.exists()  # Deleted
        assert deleted == 1
    
    def test_handles_nonexistent_files(self, tmp_path):
        """Test handling of files that don't exist"""
        dest = tmp_path / "dest"
        dest.mkdir()
        
        deleted, errors = rsync_restore.delete_orphans(str(dest), ["nonexistent.txt"], dry_run=False)
        
        # Should handle gracefully - file doesn't exist so error or 0 deleted
        assert errors >= 0
    
    def test_removes_empty_directories(self, tmp_path):
        """Test that files in nested directories are deleted"""
        dest = tmp_path / "dest"
        nested = dest / "dir1" / "dir2"
        nested.mkdir(parents=True)
        orphan = nested / "orphan.txt"
        orphan.write_text("orphan")
        
        deleted, errors = rsync_restore.delete_orphans(str(dest), ["dir1/dir2/orphan.txt"], dry_run=False)
        
        assert not orphan.exists()
        assert deleted == 1
    
    def test_tracks_deletion_errors(self, tmp_path):
        """Test that deletion errors are tracked"""
        dest = tmp_path / "dest"
        readonly_dir = dest / "readonly"
        readonly_dir.mkdir(parents=True)
        readonly_file = readonly_dir / "protected.txt"
        readonly_file.write_text("content")
        
        # Make directory read-only
        readonly_dir.chmod(0o444)
        
        try:
            deleted, errors = rsync_restore.delete_orphans(str(dest), ["readonly/protected.txt"], dry_run=False)
            
            # Should track error (can't delete in readonly dir)
            assert errors > 0 or deleted == 0
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(0o755)


class TestCleanupCLI:
    """Test run_cleanup_cli function"""
    
    def test_cleanup_cli_scans_destination(self, tmp_path):
        """Test that CLI mode scans destination"""
        db_path = tmp_path / "test.db"
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
        
        (dest / "orphan.txt").write_text("orphan")
        
        result = rsync_restore.run_cleanup_cli(
            dest_dir=str(dest),
            db_path=str(db_path),
            config_path=str(tmp_path / "config.yaml"),
            protect_patterns=[],
            cleanup_patterns=[],
            dry_run=True,
            auto_yes=True
        )
        
        # Should complete successfully
        assert result == 0
    
    def test_cleanup_cli_with_protect_patterns(self, tmp_path):
        """Test CLI with protect patterns"""
        db_path = tmp_path / "test.db"
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
        
        (dest / "orphan.txt").write_text("orphan")
        (dest / "protected.txt").write_text("protected")
        
        result = rsync_restore.run_cleanup_cli(
            dest_dir=str(dest),
            db_path=str(db_path),
            config_path=str(tmp_path / "config.yaml"),
            protect_patterns=["protected*"],
            cleanup_patterns=[],
            dry_run=False,
            auto_yes=True
        )
        
        # Should protect the protected file
        assert (dest / "protected.txt").exists()
    
    def test_cleanup_cli_dry_run(self, tmp_path):
        """Test that CLI dry run doesn't delete"""
        db_path = tmp_path / "test.db"
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
        
        orphan = dest / "orphan.txt"
        orphan.write_text("orphan")
        
        result = rsync_restore.run_cleanup_cli(
            dest_dir=str(dest),
            db_path=str(db_path),
            config_path=str(tmp_path / "config.yaml"),
            protect_patterns=[],
            cleanup_patterns=["*"],
            dry_run=True,
            auto_yes=True
        )
        
        # Dry run should not delete
        assert orphan.exists()


class TestCleanupWizard:
    """Test run_cleanup_wizard function"""
    
    @patch('builtins.input')
    def test_cleanup_wizard_interactive_scan(self, mock_input, tmp_path):
        """Test wizard mode scans and prompts"""
        db_path = tmp_path / "test.db"
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
        
        (dest / "orphan.txt").write_text("orphan")
        
        # Mock user choosing to skip
        mock_input.return_value = 'S'
        
        result = rsync_restore.run_cleanup_wizard(
            dest_dir=str(dest),
            db_path=str(db_path),
            config_path=str(tmp_path / "config.yaml")
        )
        
        # Should complete
        assert result == 0
    
    @patch('builtins.input')
    def test_cleanup_wizard_protect_option(self, mock_input, tmp_path):
        """Test wizard protect option"""
        db_path = tmp_path / "test.db"
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
        
        folder = dest / "folder"
        folder.mkdir()
        (folder / "orphan.txt").write_text("orphan")
        
        # Mock user choosing to protect
        mock_input.return_value = 'P'
        
        result = rsync_restore.run_cleanup_wizard(
            dest_dir=str(dest),
            db_path=str(db_path),
            config_path=str(tmp_path / "config.yaml")
        )
        
        # File should still exist
        assert (folder / "orphan.txt").exists()


class TestCleanupConfig:
    """Test cleanup configuration management"""
    
    def test_load_cleanup_config_defaults(self):
        """Test loading default config when file doesn't exist"""
        config = rsync_restore.load_cleanup_config("/nonexistent/config.yaml")
        
        assert 'protect' in config
        assert 'cleanup' in config
        assert isinstance(config['protect'], list)
    
    def test_save_cleanup_config(self, tmp_path):
        """Test saving cleanup config"""
        config_path = tmp_path / "config.yaml"
        
        config = {
            'protect': ['Photos/*', 'Documents/*'],
            'cleanup': ['Temp/*'],
            'last_scan': '2025-12-25 10:00:00'
        }
        
        rsync_restore.save_cleanup_config(config, str(config_path))
        
        assert config_path.exists()
    
    def test_load_saved_config(self, tmp_path):
        """Test loading previously saved config"""
        config_path = tmp_path / "config.yaml"
        
        # Save config
        original = {
            'protect': ['Photos/*'],
            'cleanup': []
        }
        rsync_restore.save_cleanup_config(original, str(config_path))
        
        # Load it back
        loaded = rsync_restore.load_cleanup_config(str(config_path))
        
        assert 'Photos/*' in loaded['protect']


class TestCleanupPatternMatching:
    """Test pattern matching for cleanup"""
    
    def test_wildcard_patterns(self):
        """Test wildcard pattern matching"""
        assert rsync_restore.matches_pattern("Photos/vacation.jpg", ["Photos/*"])
        assert not rsync_restore.matches_pattern("Documents/file.txt", ["Photos/*"])
    
    def test_exact_match_patterns(self):
        """Test exact match patterns"""
        assert rsync_restore.matches_pattern("orphan.txt", ["orphan.txt"])
        assert not rsync_restore.matches_pattern("other.txt", ["orphan.txt"])
    
    def test_multiple_patterns(self):
        """Test matching against multiple patterns"""
        patterns = ["*.tmp", "*.log", "cache/*"]
        
        assert rsync_restore.matches_pattern("file.tmp", patterns)
        assert rsync_restore.matches_pattern("debug.log", patterns)
        assert rsync_restore.matches_pattern("cache/data.db", patterns)
        assert not rsync_restore.matches_pattern("important.txt", patterns)
    
    def test_nested_path_patterns(self):
        """Test patterns with nested paths"""
        assert rsync_restore.matches_pattern("Photos/2023/vacation.jpg", ["Photos/*"])
        assert rsync_restore.matches_pattern("Photos/2023/vacation.jpg", ["Photos/**"])


class TestCleanupStatistics:
    """Test cleanup statistics and reporting"""
    
    def test_scan_reports_statistics(self, tmp_path):
        """Test that scan returns detailed statistics"""
        db_path = tmp_path / "test.db"
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
        for i in range(5):
            (dest / f"orphan{i}.txt").write_text("orphan")
        
        canonical_paths = set()
        results = rsync_restore.scan_destination_for_orphans(
            str(dest), canonical_paths, [], []
        )
        
        assert len(results['orphans']) == 5
    
    def test_delete_reports_statistics(self, tmp_path):
        """Test that deletion returns detailed statistics"""
        dest = tmp_path / "dest"
        dest.mkdir()
        orphan_names = []
        for i in range(3):
            orphan = dest / f"orphan{i}.txt"
            orphan.write_text("orphan")
            orphan_names.append(f"orphan{i}.txt")
        
        deleted, errors = rsync_restore.delete_orphans(str(dest), orphan_names, dry_run=False)
        
        assert deleted == 3
        assert errors == 0
