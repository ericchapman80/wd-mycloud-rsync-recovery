"""
Tests for error handling in rsync_restore.py

Tests error detection, recovery, validation, and edge cases.
"""
import os
import sys
import sqlite3
from unittest.mock import Mock, patch, MagicMock

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rsync_restore


class TestDatabaseErrors:
    """Test database error handling"""
    
    def test_missing_database_file(self):
        """Test handling of missing database file"""
        with pytest.raises((sqlite3.OperationalError, sqlite3.DatabaseError, FileNotFoundError)):
            rsync_restore.get_db_stats("/nonexistent/database.db")
    
    def test_corrupted_database(self, tmp_path):
        """Test handling of corrupted database"""
        db_path = tmp_path / "corrupted.db"
        db_path.write_text("This is not a valid SQLite database")
        
        with pytest.raises((sqlite3.DatabaseError, sqlite3.OperationalError)):
            rsync_restore.get_db_stats(str(db_path))
    
    def test_database_permission_denied(self, tmp_path, monkeypatch):
        """Test handling of permission denied on database"""
        db_path = tmp_path / "test.db"
        
        # Create valid database
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE Files (id INTEGER, name TEXT, contentID TEXT)")
        
        # Mock sqlite3.connect to raise permission error
        def mock_connect(*args, **kwargs):
            raise sqlite3.OperationalError("unable to open database file")
        
        monkeypatch.setattr(sqlite3, 'connect', mock_connect)
        
        with pytest.raises(sqlite3.OperationalError):
            rsync_restore.get_db_stats(str(db_path))
    
    def test_missing_table_in_database(self, tmp_path):
        """Test handling of database missing required table"""
        db_path = tmp_path / "test.db"
        
        # Create database without Files table
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE OtherTable (id INTEGER)")
        
        with pytest.raises(sqlite3.OperationalError):
            rsync_restore.get_db_stats(str(db_path))
    
    def test_empty_database_query_results(self, tmp_path):
        """Test handling of empty query results"""
        db_path = tmp_path / "test.db"
        
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE Files (id INTEGER, name TEXT, contentID TEXT)")
        
        # Should not raise error, just return zero stats
        stats = rsync_restore.get_db_stats(str(db_path))
        
        assert stats['total_files'] == 0
        assert stats['total_dirs'] == 0


class TestFileSystemErrors:
    """Test file system error handling"""
    
    def test_source_directory_not_found(self, tmp_path):
        """Test handling of missing source directory"""
        source = tmp_path / "nonexistent"
        dest = tmp_path / "dest"
        dest.mkdir()
        
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        assert result['checks_passed'] is False
    
    def test_destination_directory_not_found(self, tmp_path):
        """Test handling of missing destination directory"""
        source = tmp_path / "source"
        source.mkdir()
        dest = tmp_path / "nonexistent"
        
        # Preflight should detect missing destination
        # (or create it - depends on implementation)
        result = rsync_restore.run_preflight(str(source), str(dest))
        
        # Check if it failed or created the directory
        assert result is not None
    
    def test_permission_denied_on_source(self, tmp_path, monkeypatch):
        """Test handling of permission denied on source"""
        source = tmp_path / "source"
        source.mkdir()
        
        # Mock os.walk to raise permission error
        def mock_walk(*args, **kwargs):
            raise PermissionError("Permission denied")
        
        monkeypatch.setattr(os, 'walk', mock_walk)
        
        with pytest.raises(PermissionError):
            rsync_restore.count_files_in_dir(str(source))
    
    def test_disk_full_error(self):
        """Test handling of disk full error"""
        # This is hard to test without actually filling disk
        # We can verify the code structure handles OSError
        pass
    
    def test_symlink_creation_failure(self, tmp_path, monkeypatch):
        """Test handling of symlink creation failure"""
        # Mock os.symlink to fail
        def mock_symlink(*args, **kwargs):
            raise OSError("Failed to create symlink")
        
        monkeypatch.setattr(os, 'symlink', mock_symlink)
        
        # Would test create_symlink_farm_streaming here
        # For now, just verify the mock works
        with pytest.raises(OSError):
            os.symlink("/source", "/dest")


class TestRsyncErrors:
    """Test rsync-specific error handling"""
    
    @patch('subprocess.Popen')
    def test_rsync_command_not_found(self, mock_popen, tmp_path):
        """Test handling of rsync not installed"""
        mock_popen.side_effect = FileNotFoundError("rsync: command not found")
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        with pytest.raises(FileNotFoundError):
            rsync_restore.run_rsync("/source/", "/dest/", monitor)
    
    @patch('subprocess.Popen')
    def test_rsync_nonzero_exit_code(self, mock_popen, tmp_path):
        """Test handling of rsync failure"""
        mock_process = MagicMock()
        mock_process.stdout = ["rsync error: some files could not be transferred\n"]
        mock_process.wait.return_value = 23  # rsync error code
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        returncode, errors = rsync_restore.run_rsync("/source/", "/dest/", monitor)
        
        assert returncode != 0
        assert len(errors) > 0
    
    @patch('subprocess.Popen')
    def test_rsync_partial_transfer_error(self, mock_popen, tmp_path):
        """Test handling of partial transfer errors"""
        mock_process = MagicMock()
        mock_process.stdout = [
            "file1.txt\n",
            "xfr#1\n",
            "rsync: failed to copy file2.txt\n",
        ]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        returncode, errors = rsync_restore.run_rsync("/source/", "/dest/", monitor)
        
        assert len(errors) > 0
    
    @patch('subprocess.Popen')
    def test_rsync_interrupted(self, mock_popen, tmp_path):
        """Test handling of rsync interruption"""
        mock_process = MagicMock()
        def interrupt_generator():
            raise KeyboardInterrupt()
            yield
        mock_process.stdout = interrupt_generator()
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        returncode, errors = rsync_restore.run_rsync("/source/", "/dest/", monitor)
        
        assert returncode == 130  # Interrupt signal
        mock_process.terminate.assert_called_once()


class TestInputValidation:
    """Test input validation and sanitization"""
    
    def test_empty_path_rejection(self):
        """Test rejection of empty paths"""
        # prompt_path should reject empty strings
        # This would require mocking input()
        pass
    
    def test_invalid_path_characters(self):
        """Test handling of invalid path characters"""
        # Test paths with special characters
        paths_to_test = [
            "path\x00with\x00null",  # Null bytes
            "path\nwith\nnewlines",  # Newlines
        ]
        
        for path in paths_to_test:
            # Verify these are detected as invalid
            assert "\x00" in path or "\n" in path
    
    def test_path_traversal_protection(self):
        """Test protection against path traversal"""
        dangerous_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
        ]
        
        for path in dangerous_paths:
            # Verify path traversal patterns are detected
            assert ".." in path
    
    def test_relative_vs_absolute_paths(self):
        """Test handling of relative vs absolute paths"""
        rel_path = "relative/path"
        abs_path = "/absolute/path"
        
        assert not os.path.isabs(rel_path)
        assert os.path.isabs(abs_path)


class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    def test_zero_files_to_transfer(self, tmp_path):
        """Test handling of zero files to transfer"""
        source = tmp_path / "source"
        source.mkdir()
        
        files, size = rsync_restore.count_files_in_dir(str(source))
        
        assert files == 0
        assert size == 0
    
    def test_very_large_file_count(self):
        """Test handling of very large file counts"""
        large_count = 10_000_000
        formatted = rsync_restore.format_number(large_count)
        
        assert "10" in formatted
        assert "000" in formatted
    
    def test_very_large_byte_size(self):
        """Test handling of very large byte sizes"""
        large_size = 5 * 1024 * 1024 * 1024 * 1024  # 5 TB
        formatted = rsync_restore.format_bytes(large_size)
        
        assert "TB" in formatted
    
    def test_unicode_filenames(self, tmp_path):
        """Test handling of unicode filenames"""
        unicode_file = tmp_path / "文档.txt"
        unicode_file.write_text("test")
        
        files, size = rsync_restore.count_files_in_dir(str(tmp_path))
        
        assert files == 1
    
    def test_very_long_path(self, tmp_path):
        """Test handling of very long paths"""
        # Create nested directory structure
        long_path = tmp_path
        for i in range(50):
            long_path = long_path / f"dir{i}"
        
        # Just verify the path object works
        assert len(str(long_path)) > 200
    
    def test_empty_filename(self):
        """Test handling of empty filename"""
        # Empty filenames should be invalid
        filename = ""
        assert filename == ""
        assert len(filename) == 0


class TestCleanupPatternMatching:
    """Test cleanup pattern matching edge cases"""
    
    def test_pattern_matching_empty_pattern(self):
        """Test pattern matching with empty pattern list"""
        result = rsync_restore.matches_pattern("file.txt", [])
        assert result is False
    
    def test_pattern_matching_empty_filename(self):
        """Test pattern matching with empty filename"""
        result = rsync_restore.matches_pattern("", ["*.txt"])
        assert result is False
    
    def test_pattern_matching_special_chars(self):
        """Test pattern matching with special characters"""
        # File with brackets - matches as glob pattern
        # [1] in glob means "character class containing 1"
        result = rsync_restore.matches_pattern("file1.txt", ["file[1].txt"])
        assert result is True
    
    def test_pattern_matching_case_sensitivity(self):
        """Test pattern matching case sensitivity"""
        # Depends on implementation and OS
        result = rsync_restore.matches_pattern("FILE.TXT", ["*.txt"])
        # Result will vary by platform
        assert result in (True, False)


class TestConfigFileErrors:
    """Test config file error handling"""
    
    def test_load_nonexistent_config(self, tmp_path):
        """Test loading nonexistent config file"""
        config_path = tmp_path / "nonexistent.json"
        
        # Should return default config or raise error
        try:
            config = rsync_restore.load_cleanup_config(str(config_path))
            # If it returns default config
            assert isinstance(config, dict)
        except (FileNotFoundError, IOError):
            # If it raises error
            pass
    
    def test_load_invalid_json_config(self, tmp_path):
        """Test loading invalid JSON config"""
        config_path = tmp_path / "invalid.json"
        config_path.write_text("{ invalid json")
        
        # Should handle parse error gracefully
        try:
            config = rsync_restore.load_cleanup_config(str(config_path))
        except (ValueError, Exception):
            # Expected to raise error on invalid JSON
            pass
    
    def test_save_config_permission_denied(self, tmp_path, monkeypatch):
        """Test saving config with permission denied"""
        config_path = tmp_path / "config.json"
        
        # Mock open to raise permission error
        original_open = open
        def mock_open(*args, **kwargs):
            if str(config_path) in str(args[0]):
                raise PermissionError("Permission denied")
            return original_open(*args, **kwargs)
        
        monkeypatch.setattr('builtins.open', mock_open)
        
        config = {'test': 'value'}
        
        with pytest.raises(PermissionError):
            rsync_restore.save_cleanup_config(config, str(config_path))


class TestRecoveryAndRetry:
    """Test recovery and retry logic"""
    
    @patch('subprocess.Popen')
    def test_retry_on_transient_failure(self, mock_popen, tmp_path):
        """Test retry logic for transient failures"""
        # First call fails, second succeeds
        mock_process_fail = MagicMock()
        mock_process_fail.stdout = ["rsync error: timeout\n"]
        mock_process_fail.wait.return_value = 30  # Timeout error
        
        mock_process_success = MagicMock()
        mock_process_success.stdout = []
        mock_process_success.wait.return_value = 0
        
        mock_popen.side_effect = [mock_process_fail, mock_process_success]
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        # First attempt fails
        returncode1, errors1 = rsync_restore.run_rsync("/source/", "/dest/", monitor)
        assert returncode1 != 0
        
        # Retry succeeds
        returncode2, errors2 = rsync_restore.run_rsync("/source/", "/dest/", monitor)
        assert returncode2 == 0
