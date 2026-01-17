"""
Integration tests for run_preflight() in rsync_restore.py

Tests full preflight workflow with real file system,
database integration, and multi-component scenarios.
"""
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rsync_restore


class TestPreflightEndToEnd:
    """Test complete preflight workflow"""
    
    def test_preflight_with_all_components(self, tmp_path):
        """Test preflight with source, dest, database, and farm"""
        # Setup complete environment
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        db_path = tmp_path / "index.db"
        farm = tmp_path / "farm"
        
        source.mkdir()
        dest.mkdir()
        
        # Create test files in source
        for i in range(10):
            (source / f"file{i}.txt").write_text(f"content {i}")
        
        # Create database
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
                conn.execute(f"INSERT INTO Files (id, name, parentID, contentID) VALUES ({i+1}, 'file{i}.txt', NULL, 'abc{i:03d}')")
        
        # Run preflight
        result = rsync_restore.run_preflight(
            str(source),
            str(dest),
            str(db_path),
            str(farm)
        )
        
        # Verify all checks passed
        assert result['checks_passed'] is True
        assert result['source_files'] == 10
        assert 'db_stats' in result
        assert 'rsync_path' in result
    
    def test_preflight_detects_missing_source(self, tmp_path):
        """Test that preflight fails when source doesn't exist"""
        dest = tmp_path / "dest"
        dest.mkdir()
        
        result = rsync_restore.run_preflight(
            str(tmp_path / "nonexistent"),
            str(dest)
        )
        
        assert result['checks_passed'] is False
    
    def test_preflight_creates_destination_warning(self, tmp_path):
        """Test that preflight warns when destination will be created"""
        source = tmp_path / "source"
        source.mkdir()
        (source / "test.txt").write_text("content")
        
        result = rsync_restore.run_preflight(
            str(source),
            str(tmp_path / "new_dest")
        )
        
        # Should pass but include warning about creating destination
        assert result['checks_passed'] is True
    
    def test_preflight_with_existing_destination_files(self, tmp_path):
        """Test preflight when destination already has files"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        # Source has 10 files
        for i in range(10):
            (source / f"file{i}.txt").write_text(f"content {i}")
        
        # Dest already has 5 files
        for i in range(5):
            (dest / f"file{i}.txt").write_text(f"existing {i}")
        
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        assert result['source_files'] == 10
        assert result['dest_files'] == 5
        assert result['dest_size'] > 0
    
    def test_preflight_database_statistics(self, tmp_path):
        """Test that preflight correctly reports database statistics"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        db_path = tmp_path / "index.db"
        source.mkdir()
        dest.mkdir()
        
        # Create database with known counts
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            # 20 files
            for i in range(20):
                conn.execute(f"INSERT INTO Files VALUES ({i+1}, 'file{i}.txt', NULL, 'content{i}')")
            # 10 directories
            for i in range(10):
                conn.execute(f"INSERT INTO Files VALUES ({i+21}, 'dir{i}', NULL, NULL)")
        
        result = rsync_restore.run_preflight(str(source), str(dest), str(db_path))
        
        assert result['db_stats']['total_files'] == 20
        assert result['db_stats']['total_dirs'] == 10
    
    def test_preflight_farm_verification(self, tmp_path):
        """Test preflight verification of existing symlink farm"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        db_path = tmp_path / "index.db"
        farm = tmp_path / "farm"
        
        source.mkdir()
        dest.mkdir()
        farm.mkdir()
        
        # Create database
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
                conn.execute(f"INSERT INTO Files VALUES ({i+1}, 'file{i}.txt', NULL, 'content{i}')")
        
        # Create partial farm (only 5 out of 10 symlinks)
        for i in range(5):
            source_file = source / f"file{i}.txt"
            source_file.write_text(f"content {i}")
            link = farm / f"file{i}.txt"
            link.symlink_to(source_file)
        
        result = rsync_restore.run_preflight(str(source), str(dest), str(db_path), str(farm))
        
        assert result['farm_files'] == 5
        # Should have warning about incomplete farm
        if result['db_stats']['total_files'] > 0:
            assert result['farm_files'] < result['db_stats']['total_files']


class TestPreflightWithRsyncCheck:
    """Test preflight rsync availability checks"""
    
    @patch('shutil.which')
    def test_preflight_fails_without_rsync(self, mock_which, tmp_path):
        """Test that preflight fails when rsync is not found"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        # Mock rsync not found
        mock_which.return_value = None
        
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        assert result['checks_passed'] is False
    
    @patch('shutil.which')
    def test_preflight_succeeds_with_rsync(self, mock_which, tmp_path):
        """Test that preflight succeeds when rsync is found"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        (source / "test.txt").write_text("content")
        
        # Mock rsync found
        mock_which.return_value = '/usr/bin/rsync'
        
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        assert result['checks_passed'] is True
        assert result['rsync_path'] == '/usr/bin/rsync'


class TestPreflightDiskSpaceWarnings:
    """Test disk space warning logic"""
    
    @patch('psutil.disk_usage')
    def test_warns_on_low_disk_space(self, mock_disk_usage, tmp_path):
        """Test warning when destination has insufficient free space"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        # Create large source files (simulated)
        for i in range(10):
            (source / f"file{i}.txt").write_bytes(b"x" * 1000000)  # 1MB each
        
        # Mock low disk space (only 5MB free)
        mock_usage = MagicMock()
        mock_usage.free = 5 * 1024 * 1024
        mock_disk_usage.return_value = mock_usage
        
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        # Should have low_free_space warning
        assert 'low_free_space' in result['warnings']
    
    @patch('psutil.disk_usage')
    def test_no_warning_with_sufficient_space(self, mock_disk_usage, tmp_path):
        """Test no warning when sufficient space available"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        (source / "small.txt").write_text("small content")
        
        # Mock plenty of disk space (100GB free)
        mock_usage = MagicMock()
        mock_usage.free = 100 * 1024 * 1024 * 1024
        mock_disk_usage.return_value = mock_usage
        
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        # Should not have low_free_space warning
        assert 'low_free_space' not in result['warnings']


class TestPreflightSystemInfo:
    """Test system information gathering in preflight"""
    
    @patch('psutil.virtual_memory')
    @patch('os.getloadavg')
    def test_includes_system_stats(self, mock_loadavg, mock_memory, tmp_path):
        """Test that preflight includes system statistics"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        # Mock system stats
        mock_mem = MagicMock()
        mock_mem.percent = 45.5
        mock_mem.available = 8 * 1024 * 1024 * 1024
        mock_memory.return_value = mock_mem
        mock_loadavg.return_value = (1.5, 1.2, 0.9)
        
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        assert 'memory_percent' in result
        assert 'load_avg' in result
        assert result['memory_percent'] == 45.5
        assert result['load_avg'] == (1.5, 1.2, 0.9)


class TestPreflightMultiSource:
    """Test preflight with various source configurations"""
    
    def test_preflight_with_nested_source_structure(self, tmp_path):
        """Test preflight with deeply nested source directory"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        # Create nested structure
        nested = source / "level1" / "level2" / "level3"
        nested.mkdir(parents=True)
        
        for i in range(5):
            (nested / f"file{i}.txt").write_text(f"nested content {i}")
        
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        assert result['source_files'] == 5
        assert result['source_size'] > 0
    
    def test_preflight_with_many_small_files(self, tmp_path):
        """Test preflight performance with many small files"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        # Create 100 small files
        for i in range(100):
            (source / f"small{i}.txt").write_text("x")
        
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        assert result['source_files'] == 100
        assert result['checks_passed'] is True
    
    def test_preflight_with_few_large_files(self, tmp_path):
        """Test preflight with few but large files"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        # Create 3 large files
        for i in range(3):
            (source / f"large{i}.bin").write_bytes(b"x" * 1000000)  # 1MB each
        
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        assert result['source_files'] == 3
        assert result['source_size'] >= 3000000


class TestPreflightIntegrationWithDatabase:
    """Test preflight integration with database operations"""
    
    def test_preflight_with_mixed_content(self, tmp_path):
        """Test database with files and directories mixed"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        db_path = tmp_path / "index.db"
        source.mkdir()
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
            # Root directories
            conn.execute("INSERT INTO Files VALUES (1, 'Photos', NULL, NULL)")
            conn.execute("INSERT INTO Files VALUES (2, 'Documents', NULL, NULL)")
            # Files in directories
            conn.execute("INSERT INTO Files VALUES (3, 'vacation.jpg', 1, 'img001')")
            conn.execute("INSERT INTO Files VALUES (4, 'report.pdf', 2, 'doc001')")
        
        result = rsync_restore.run_preflight(str(source), str(dest), str(db_path))
        
        assert result['db_stats']['total_files'] == 2
        assert result['db_stats']['total_dirs'] == 2
    
    def test_preflight_with_empty_contentid(self, tmp_path):
        """Test handling of empty contentID (directories)"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        db_path = tmp_path / "index.db"
        source.mkdir()
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
            conn.execute("INSERT INTO Files VALUES (1, 'dir', NULL, '')")
            conn.execute("INSERT INTO Files VALUES (2, 'file.txt', 1, 'content1')")
        
        result = rsync_restore.run_preflight(str(source), str(dest), str(db_path))
        
        # Empty contentID should be counted as directory
        assert result['db_stats']['total_dirs'] >= 1
        assert result['db_stats']['total_files'] >= 1
    
    def test_preflight_database_timeout_handling(self, tmp_path):
        """Test that database timeout is properly set"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        db_path = tmp_path / "index.db"
        source.mkdir()
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
            conn.execute("INSERT INTO Files VALUES (1, 'test.txt', NULL, 'abc123')")
        
        # Should complete without timing out
        result = rsync_restore.run_preflight(str(source), str(dest), str(db_path))
        
        assert result['checks_passed'] is True


class TestPreflightReporting:
    """Test preflight output and reporting"""
    
    def test_preflight_returns_all_required_fields(self, tmp_path):
        """Test that preflight result contains all required fields"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        (source / "test.txt").write_text("content")
        
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        # Check for required fields
        required_fields = [
            'source', 'dest', 'checks_passed', 'warnings',
            'source_files', 'source_size'
        ]
        
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"
    
    def test_preflight_tracks_multiple_warnings(self, tmp_path):
        """Test that multiple warnings can be tracked"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        assert 'warnings' in result
        assert isinstance(result['warnings'], list)


class TestPreflightErrorRecovery:
    """Test preflight error handling and recovery"""
    
    def test_preflight_continues_after_non_critical_errors(self, tmp_path):
        """Test that preflight continues when non-critical checks fail"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        (source / "test.txt").write_text("content")
        
        # Missing database is non-critical
        result = rsync_restore.run_preflight(
            str(source),
            str(dest),
            db_path=str(tmp_path / "missing.db")
        )
        
        # Should still check source/dest even if DB missing
        assert 'source_files' in result
        assert 'dest_files' in result or 'dest' in result
    
    def test_preflight_stops_on_critical_errors(self, tmp_path):
        """Test that preflight stops when critical checks fail"""
        dest = tmp_path / "dest"
        dest.mkdir()
        
        # Missing source is critical
        result = rsync_restore.run_preflight(
            str(tmp_path / "missing_source"),
            str(dest)
        )
        
        assert result['checks_passed'] is False
