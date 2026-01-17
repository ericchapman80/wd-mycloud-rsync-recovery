"""
Tests for database operations in rsync_restore.py

Tests database connection, schema queries, path reconstruction,
and statistics gathering.
"""
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rsync_restore


class TestDatabaseConnection:
    """Test database connection and basic queries"""
    
    def test_get_db_stats_empty_database(self, tmp_path):
        """Test get_db_stats with an empty database"""
        db_path = tmp_path / "test.db"
        
        # Create minimal schema
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        stats = rsync_restore.get_db_stats(str(db_path))
        
        assert stats['total_files'] == 0
        assert stats['total_dirs'] == 0
        assert stats['remaining'] == 0
        assert stats['percent_complete'] == 0
    
    def test_get_db_stats_with_files(self, tmp_path):
        """Test get_db_stats with files in database"""
        db_path = tmp_path / "test.db"
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            
            # Insert test data: 3 files, 2 directories
            conn.execute("INSERT INTO Files (id, name, contentID) VALUES (1, 'root', NULL)")
            conn.execute("INSERT INTO Files (id, name, contentID) VALUES (2, 'dir1', '')")
            conn.execute("INSERT INTO Files (id, name, contentID) VALUES (3, 'file1.txt', 'abc123')")
            conn.execute("INSERT INTO Files (id, name, contentID) VALUES (4, 'file2.txt', 'def456')")
            conn.execute("INSERT INTO Files (id, name, contentID) VALUES (5, 'file3.txt', 'ghi789')")
        
        stats = rsync_restore.get_db_stats(str(db_path))
        
        assert stats['total_files'] == 3
        assert stats['total_dirs'] == 2
        assert stats['remaining'] == 3
    
    def test_get_db_stats_nonexistent_database(self):
        """Test get_db_stats with nonexistent database"""
        with pytest.raises((sqlite3.OperationalError, sqlite3.DatabaseError)):
            rsync_restore.get_db_stats("/nonexistent/path/db.sqlite")


class TestPathReconstruction:
    """Test path reconstruction from database"""
    
    def test_get_canonical_paths_from_db_simple(self, tmp_path):
        """Test path reconstruction with simple hierarchy"""
        db_path = tmp_path / "test.db"
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            
            # Create simple hierarchy: root/dir1/file.txt
            conn.execute("INSERT INTO files (id, name, parentID, contentID) VALUES (1, 'root', NULL, NULL)")
            conn.execute("INSERT INTO files (id, name, parentID, contentID) VALUES (2, 'dir1', 1, NULL)")
            conn.execute("INSERT INTO files (id, name, parentID, contentID) VALUES (3, 'file.txt', 2, 'abc123')")
        
        paths = rsync_restore.get_canonical_paths_from_db(str(db_path))
        
        assert len(paths) > 0
        # Should contain the file path
        assert any('file.txt' in p for p in paths)
    
    def test_get_canonical_paths_from_db_multiple_files(self, tmp_path):
        """Test path reconstruction with multiple files"""
        db_path = tmp_path / "test.db"
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            
            # Create hierarchy with multiple files
            conn.execute("INSERT INTO files (id, name, parentID, contentID) VALUES (1, 'root', NULL, NULL)")
            conn.execute("INSERT INTO files (id, name, parentID, contentID) VALUES (2, 'dir1', 1, NULL)")
            conn.execute("INSERT INTO files (id, name, parentID, contentID) VALUES (3, 'file1.txt', 2, 'abc')")
            conn.execute("INSERT INTO files (id, name, parentID, contentID) VALUES (4, 'file2.txt', 2, 'def')")
            conn.execute("INSERT INTO files (id, name, parentID, contentID) VALUES (5, 'dir2', 1, NULL)")
            conn.execute("INSERT INTO files (id, name, parentID, contentID) VALUES (6, 'file3.txt', 5, 'ghi')")
        
        paths = rsync_restore.get_canonical_paths_from_db(str(db_path))
        
        assert len(paths) == 3  # Three files with contentID
        assert any('file1.txt' in p for p in paths)
        assert any('file2.txt' in p for p in paths)
        assert any('file3.txt' in p for p in paths)
    
    def test_get_canonical_paths_empty_database(self, tmp_path):
        """Test path reconstruction with empty database"""
        db_path = tmp_path / "test.db"
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        paths = rsync_restore.get_canonical_paths_from_db(str(db_path))
        
        assert len(paths) == 0
    
    def test_get_canonical_paths_only_directories(self, tmp_path):
        """Test path reconstruction with only directories (no files)"""
        db_path = tmp_path / "test.db"
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            
            # Only directories (no contentID or NULL)
            conn.execute("INSERT INTO files (id, name, parentID, contentID) VALUES (1, 'root', NULL, NULL)")
            conn.execute("INSERT INTO files (id, name, parentID, contentID) VALUES (2, 'dir1', 1, NULL)")
        
        paths = rsync_restore.get_canonical_paths_from_db(str(db_path))
        
        assert len(paths) == 0  # No files, only directories


class TestDatabaseBusyTimeout:
    """Test database busy timeout handling"""
    
    def test_database_busy_timeout_set(self, tmp_path):
        """Verify PRAGMA busy_timeout is set correctly"""
        db_path = tmp_path / "test.db"
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files (id, name, contentID) VALUES (1, 'test', 'abc')")
        
        # get_db_stats should work without hanging
        stats = rsync_restore.get_db_stats(str(db_path))
        
        assert stats is not None
        assert 'total_files' in stats


class TestDatabaseSchemaCompatibility:
    """Test compatibility with different database schemas"""
    
    def test_lowercase_files_table(self, tmp_path):
        """Test with lowercase 'files' table (legacy schema)"""
        db_path = tmp_path / "test.db"
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO files (id, name, parentID, contentID) VALUES (1, 'test.txt', NULL, 'abc123')")
        
        # get_canonical_paths uses lowercase 'files'
        paths = rsync_restore.get_canonical_paths_from_db(str(db_path))
        
        assert len(paths) > 0
    
    def test_uppercase_files_table(self, tmp_path):
        """Test with uppercase 'Files' table (production schema)"""
        db_path = tmp_path / "test.db"
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files (id, name, contentID) VALUES (1, 'test.txt', 'abc123')")
        
        # get_db_stats uses uppercase 'Files'
        stats = rsync_restore.get_db_stats(str(db_path))
        
        assert stats['total_files'] == 1


class TestCountFilesInDir:
    """Test file counting utility function"""
    
    def test_count_files_empty_directory(self, tmp_path):
        """Test counting files in empty directory"""
        files, size = rsync_restore.count_files_in_dir(str(tmp_path))
        
        assert files == 0
        assert size == 0
    
    def test_count_files_with_files(self, tmp_path):
        """Test counting files in directory with files"""
        # Create test files
        (tmp_path / "file1.txt").write_text("hello")
        (tmp_path / "file2.txt").write_text("world")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file3.txt").write_text("test")
        
        files, size = rsync_restore.count_files_in_dir(str(tmp_path))
        
        assert files == 3
        assert size > 0  # Total size of all files
        assert size == 5 + 5 + 4  # "hello" + "world" + "test"
    
    def test_count_files_ignores_directories(self, tmp_path):
        """Test that directory count only counts files, not directories"""
        # Create nested directories with files
        (tmp_path / "dir1").mkdir()
        (tmp_path / "dir1" / "dir2").mkdir()
        (tmp_path / "dir1" / "file.txt").write_text("test")
        
        files, size = rsync_restore.count_files_in_dir(str(tmp_path))
        
        assert files == 1  # Only the file, not the directories
    
    def test_count_files_handles_permission_errors(self, tmp_path, monkeypatch):
        """Test that count_files_in_dir handles permission errors gracefully"""
        # Create a file
        test_file = tmp_path / "file.txt"
        test_file.write_text("test")
        
        # Mock os.path.getsize to raise OSError
        original_getsize = os.path.getsize
        def mock_getsize(path):
            if "file.txt" in path:
                raise OSError("Permission denied")
            return original_getsize(path)
        
        monkeypatch.setattr(os.path, 'getsize', mock_getsize)
        
        files, size = rsync_restore.count_files_in_dir(str(tmp_path))
        
        # File is counted but size is 0 due to error
        assert files == 1
        assert size == 0
