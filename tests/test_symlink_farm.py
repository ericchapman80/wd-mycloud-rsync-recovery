"""
Tests for symlink farm creation in rsync_restore.py

Tests the create_symlink_farm_streaming() function which creates
a directory tree of symlinks based on database paths.
"""
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rsync_restore


class TestSymlinkFarmBasics:
    """Test basic symlink farm creation"""
    
    def test_creates_farm_directory(self, tmp_path):
        """Test that farm directory is created if missing"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        
        # Create minimal database
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'test.txt', NULL, 'abc123')")
        
        # Create source file
        (source / "ab" / "abc123").mkdir(parents=True)
        (source / "ab" / "abc123" / "abc123").write_text("content")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm),
            limit=0
        )
        
        assert os.path.isdir(str(farm))
        assert result['created'] > 0
    
    def test_creates_symlinks_for_files(self, tmp_path):
        """Test that symlinks are created for each file"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'file1.txt', NULL, 'aaa111')")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (2, 'file2.txt', NULL, 'bbb222')")
        
        # Create source files
        (source / "aa" / "aaa111").mkdir(parents=True)
        (source / "aa" / "aaa111" / "aaa111").write_text("content1")
        (source / "bb" / "bbb222").mkdir(parents=True)
        (source / "bb" / "bbb222" / "bbb222").write_text("content2")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert result['created'] == 2
        assert os.path.islink(str(farm / "file1.txt"))
        assert os.path.islink(str(farm / "file2.txt"))
    
    def test_skips_directories(self, tmp_path):
        """Test that directories (no contentID) are skipped"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            # Directory entries have NULL or empty contentID
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'dir1', NULL, NULL)")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (2, 'dir2', NULL, '')")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (3, 'file.txt', 1, 'abc123')")
        
        (source / "ab" / "abc123").mkdir(parents=True)
        (source / "ab" / "abc123" / "abc123").write_text("content")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        # Only 1 file, 2 directories skipped
        assert result['created'] == 1
        assert not os.path.exists(str(farm / "dir1"))
        assert not os.path.exists(str(farm / "dir2"))
    
    def test_creates_nested_directory_structure(self, tmp_path):
        """Test that nested directories are created for paths"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
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
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (2, '2023', 1, NULL)")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (3, 'vacation.jpg', 2, 'xyz789')")
        
        (source / "xy" / "xyz789").mkdir(parents=True)
        (source / "xy" / "xyz789" / "xyz789").write_text("image")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert result['created'] == 1
        assert os.path.isdir(str(farm / "Photos"))
        assert os.path.isdir(str(farm / "Photos" / "2023"))
        assert os.path.islink(str(farm / "Photos" / "2023" / "vacation.jpg"))


class TestSymlinkFarmPathReconstruction:
    """Test path reconstruction from database"""
    
    def test_reconstructs_simple_paths(self, tmp_path):
        """Test reconstruction of simple file paths"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'root.txt', NULL, 'abc123')")
        
        (source / "ab" / "abc123").mkdir(parents=True)
        (source / "ab" / "abc123" / "abc123").write_text("content")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        link = farm / "root.txt"
        assert os.path.islink(str(link))
        assert os.readlink(str(link)).endswith("abc123")
    
    def test_reconstructs_deep_nested_paths(self, tmp_path):
        """Test reconstruction of deeply nested paths"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            # Create deep hierarchy: root/a/b/c/d/file.txt
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'a', NULL, NULL)")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (2, 'b', 1, NULL)")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (3, 'c', 2, NULL)")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (4, 'd', 3, NULL)")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (5, 'deep.txt', 4, 'deep99')")
        
        (source / "de" / "deep99").mkdir(parents=True)
        (source / "de" / "deep99" / "deep99").write_text("content")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert result['created'] == 1
        deep_file = farm / "a" / "b" / "c" / "d" / "deep.txt"
        assert os.path.islink(str(deep_file))
    
    def test_handles_multiple_files_same_directory(self, tmp_path):
        """Test multiple files in same directory"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'docs', NULL, NULL)")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (2, 'file1.pdf', 1, 'aaa111')")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (3, 'file2.pdf', 1, 'bbb222')")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (4, 'file3.pdf', 1, 'ccc333')")
        
        for cid in ['aaa111', 'bbb222', 'ccc333']:
            (source / cid[:2] / cid).mkdir(parents=True)
            (source / cid[:2] / cid / cid).write_text("content")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert result['created'] == 3
        assert os.path.islink(str(farm / "docs" / "file1.pdf"))
        assert os.path.islink(str(farm / "docs" / "file2.pdf"))
        assert os.path.islink(str(farm / "docs" / "file3.pdf"))


class TestSymlinkFarmEdgeCases:
    """Test edge cases and error conditions"""
    
    def test_handles_missing_source_files(self, tmp_path):
        """Test handling when source files don't exist"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'missing.txt', NULL, 'xyz999')")
        
        # Don't create source file
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        # Should report as missing
        assert result['missing'] == 1
        assert result['created'] == 0
    
    def test_skips_existing_symlinks(self, tmp_path):
        """Test that existing symlinks are skipped"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'exists.txt', NULL, 'abc123')")
        
        (source / "ab" / "abc123").mkdir(parents=True)
        source_file = source / "ab" / "abc123" / "abc123"
        source_file.write_text("content")
        
        # Create symlink already
        link = farm / "exists.txt"
        link.symlink_to(source_file)
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert result['skipped'] == 1
        assert result['created'] == 0
    
    def test_handles_special_characters_in_names(self, tmp_path):
        """Test files with special characters in names"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            # File with spaces and special chars
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'my file (2023).txt', NULL, 'abc123')")
        
        (source / "ab" / "abc123").mkdir(parents=True)
        (source / "ab" / "abc123" / "abc123").write_text("content")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert result['created'] == 1
        assert os.path.islink(str(farm / "my file (2023).txt"))
    
    def test_respects_limit_parameter(self, tmp_path):
        """Test that limit parameter restricts number of symlinks"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            for i in range(10):
                cid = f"file{i:03d}"
                conn.execute(f"INSERT INTO Files (id, name, parentID, contentID) VALUES ({i+1}, 'file{i}.txt', NULL, '{cid}')")
                (source / cid[:2] / cid).mkdir(parents=True)
                (source / cid[:2] / cid / cid).write_text("content")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm),
            limit=5
        )
        
        assert result['created'] == 5
        assert result['total_processed'] == 5
    
    def test_empty_database(self, tmp_path):
        """Test handling of empty database"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert result['created'] == 0
        assert result['total_processed'] == 0


class TestSymlinkFarmStatistics:
    """Test statistics and reporting"""
    
    def test_returns_correct_statistics(self, tmp_path):
        """Test that statistics are accurate"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'file1.txt', NULL, 'aaa111')")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (2, 'file2.txt', NULL, 'bbb222')")
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (3, 'file3.txt', NULL, 'ccc333')")
        
        # Only create 2 out of 3 source files
        for cid in ['aaa111', 'bbb222']:
            (source / cid[:2] / cid).mkdir(parents=True)
            (source / cid[:2] / cid / cid).write_text("content")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert result['created'] == 2
        assert result['missing'] == 1
        assert result['total_processed'] == 3
    
    def test_tracks_errors(self, tmp_path):
        """Test that errors are tracked"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'test.txt', NULL, 'abc123')")
        
        (source / "ab" / "abc123").mkdir(parents=True)
        (source / "ab" / "abc123" / "abc123").write_text("content")
        
        # Create a regular file where symlink should go (will cause error)
        (farm / "test.txt").write_text("blocking file")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        # Should have an error due to existing file
        assert result['created'] == 0
        assert result['errors'] > 0


class TestSymlinkFarmPerformance:
    """Test performance-related aspects"""
    
    def test_streaming_processes_incrementally(self, tmp_path):
        """Test that streaming processes files incrementally"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            # Create many files
            for i in range(100):
                cid = f"f{i:05d}"
                conn.execute(f"INSERT INTO Files (id, name, parentID, contentID) VALUES ({i+1}, 'file{i}.txt', NULL, '{cid}')")
                (source / cid[:2] / cid).mkdir(parents=True)
                (source / cid[:2] / cid / cid).write_text("content")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm),
            batch_size=10
        )
        
        assert result['created'] == 100
    
    def test_handles_large_path_hierarchies(self, tmp_path):
        """Test handling of databases with many nested levels"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            # Create 10 levels deep
            parent_id = None
            for i in range(10):
                conn.execute(f"INSERT INTO Files (id, name, parentID, contentID) VALUES ({i+1}, 'dir{i}', {parent_id if parent_id else 'NULL'}, NULL)")
                parent_id = i + 1
            
            # Add file at deepest level
            conn.execute(f"INSERT INTO Files (id, name, parentID, contentID) VALUES (11, 'deep.txt', {parent_id}, 'deep99')")
        
        (source / "de" / "deep99").mkdir(parents=True)
        (source / "de" / "deep99" / "deep99").write_text("content")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert result['created'] == 1


class TestSymlinkFarmSanitization:
    """Test sanitization of pipe characters"""
    
    def test_sanitizes_pipe_characters_when_enabled(self, tmp_path):
        """Test that pipe characters are replaced when sanitization enabled"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'file|with|pipes.txt', NULL, 'abc123')")
        
        (source / "ab" / "abc123").mkdir(parents=True)
        (source / "ab" / "abc123" / "abc123").write_text("content")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm),
            sanitize_pipes=True
        )
        
        assert result['created'] == 1
        # Pipes should be replaced with underscores
        assert os.path.islink(str(farm / "file_with_pipes.txt"))
    
    def test_preserves_pipes_when_disabled(self, tmp_path):
        """Test that pipe characters are preserved when sanitization disabled"""
        db_path = tmp_path / "test.db"
        source = tmp_path / "source"
        farm = tmp_path / "farm"
        source.mkdir()
        farm.mkdir()
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files (id, name, parentID, contentID) VALUES (1, 'file|with|pipes.txt', NULL, 'abc123')")
        
        (source / "ab" / "abc123").mkdir(parents=True)
        (source / "ab" / "abc123" / "abc123").write_text("content")
        
        result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm),
            sanitize_pipes=False
        )
        
        assert result['created'] == 1
        # Pipes should be preserved (if filesystem allows)
        # On some filesystems this might fail, so check for either
        assert os.path.islink(str(farm / "file|with|pipes.txt")) or result['errors'] > 0
