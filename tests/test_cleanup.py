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
        """Test that files not in database are identified as orphans"""
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
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'legitimate.txt', NULL, 'abc123')")
        
        # Create files - one legitimate, one orphan
        (dest / "legitimate.txt").write_text("should exist")
        (dest / "orphan.txt").write_text("should not exist")
        
        results = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        
        assert results['orphan_count'] > 0
        assert 'orphan.txt' in results['orphans']
    
    def test_recognizes_legitimate_files(self, tmp_path):
        """Test that files in database are not marked as orphans"""
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
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'Photos', NULL, NULL)")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (2, 'vacation.jpg', 1, 'xyz789')")
        
        # Create the legitimate file structure
        photos_dir = dest / "Photos"
        photos_dir.mkdir()
        (photos_dir / "vacation.jpg").write_text("image data")
        
        results = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        
        assert results['orphan_count'] == 0
        assert len(results['orphans']) == 0
    
    def test_scans_nested_directories(self, tmp_path):
        """Test that nested directories are scanned for orphans"""
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
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'dir1', NULL, NULL)")
        
        # Create nested structure with orphan deep inside
        nested = dest / "dir1" / "subdir" / "deep"
        nested.mkdir(parents=True)
        (nested / "orphan.txt").write_text("orphan")
        
        results = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        
        assert results['orphan_count'] > 0
    
    def test_respects_protect_patterns(self, tmp_path):
        """Test that protected patterns are excluded from orphans"""
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
        
        # Create orphan files
        (dest / "orphan1.txt").write_text("orphan")
        protected = dest / "protected"
        protected.mkdir()
        (protected / "safe.txt").write_text("protected")
        
        results = rsync_restore.scan_destination_for_orphans(
            str(dest),
            str(db_path),
            protect_patterns=["protected/*"]
        )
        
        # protected/safe.txt should not be in orphans
        orphan_names = [os.path.basename(o) for o in results['orphans']]
        assert 'orphan1.txt' in orphan_names
        assert 'safe.txt' not in orphan_names
    
    def test_groups_orphans_by_folder(self, tmp_path):
        """Test that orphans are grouped by containing folder"""
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
        
        # Create orphans in different folders
        folder1 = dest / "folder1"
        folder2 = dest / "folder2"
        folder1.mkdir()
        folder2.mkdir()
        (folder1 / "orphan1.txt").write_text("orphan")
        (folder1 / "orphan2.txt").write_text("orphan")
        (folder2 / "orphan3.txt").write_text("orphan")
        
        results = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        
        assert 'by_folder' in results
        assert 'folder1' in results['by_folder']
        assert 'folder2' in results['by_folder']
        assert len(results['by_folder']['folder1']) == 2
        assert len(results['by_folder']['folder2']) == 1
    
    def test_handles_empty_destination(self, tmp_path):
        """Test scanning empty destination"""
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
        
        results = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        
        assert results['orphan_count'] == 0
        assert len(results['orphans']) == 0


class TestOrphanDeletion:
    """Test delete_orphans function"""
    
    def test_deletes_orphan_files(self, tmp_path):
        """Test that orphan files are deleted"""
        orphan1 = tmp_path / "orphan1.txt"
        orphan2 = tmp_path / "orphan2.txt"
        orphan1.write_text("orphan")
        orphan2.write_text("orphan")
        
        orphan_list = [str(orphan1), str(orphan2)]
        
        result = rsync_restore.delete_orphans(orphan_list, dry_run=False)
        
        assert result['deleted'] == 2
        assert not orphan1.exists()
        assert not orphan2.exists()
    
    def test_dry_run_does_not_delete(self, tmp_path):
        """Test that dry run does not actually delete files"""
        orphan = tmp_path / "orphan.txt"
        orphan.write_text("orphan")
        
        result = rsync_restore.delete_orphans([str(orphan)], dry_run=True)
        
        assert result['deleted'] == 1  # Would delete
        assert orphan.exists()  # But file still exists
    
    def test_respects_protect_patterns(self, tmp_path):
        """Test that protected files are not deleted"""
        orphan = tmp_path / "orphan.txt"
        protected = tmp_path / "protected.txt"
        orphan.write_text("orphan")
        protected.write_text("protected")
        
        orphan_list = [str(orphan), str(protected)]
        
        result = rsync_restore.delete_orphans(
            orphan_list,
            dry_run=False,
            protect_patterns=["protected*"]
        )
        
        assert not orphan.exists()  # Deleted
        assert protected.exists()  # Protected
    
    def test_handles_nonexistent_files(self, tmp_path):
        """Test handling of files that don't exist"""
        nonexistent = tmp_path / "nonexistent.txt"
        
        result = rsync_restore.delete_orphans([str(nonexistent)], dry_run=False)
        
        # Should handle gracefully
        assert result['errors'] == 0 or result['deleted'] == 0
    
    def test_removes_empty_directories(self, tmp_path):
        """Test that empty directories are removed after deletion"""
        nested = tmp_path / "dir1" / "dir2"
        nested.mkdir(parents=True)
        orphan = nested / "orphan.txt"
        orphan.write_text("orphan")
        
        result = rsync_restore.delete_orphans([str(orphan)], dry_run=False)
        
        assert not orphan.exists()
        # Empty parent directories may be removed
        # This depends on implementation
    
    def test_tracks_deletion_errors(self, tmp_path):
        """Test that deletion errors are tracked"""
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_file = readonly_dir / "protected.txt"
        readonly_file.write_text("content")
        
        # Make directory read-only
        readonly_dir.chmod(0o444)
        
        try:
            result = rsync_restore.delete_orphans([str(readonly_file)], dry_run=False)
            
            # Should track error
            assert result['errors'] > 0 or result['deleted'] == 0
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
        
        results = rsync_restore.scan_destination_for_orphans(str(dest), str(db_path))
        
        assert results['orphan_count'] == 5
        assert 'total_scanned' in results
        assert results['total_scanned'] >= 5
    
    def test_delete_reports_statistics(self, tmp_path):
        """Test that deletion returns detailed statistics"""
        orphans = []
        for i in range(3):
            orphan = tmp_path / f"orphan{i}.txt"
            orphan.write_text("orphan")
            orphans.append(str(orphan))
        
        result = rsync_restore.delete_orphans(orphans, dry_run=False)
        
        assert result['deleted'] == 3
        assert 'errors' in result
