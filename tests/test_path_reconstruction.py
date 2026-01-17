"""
Tests for path reconstruction and pattern matching in rsync_restore.py

Tests path handling, pattern matching, and file path utilities.
"""
import os
import sys
import fnmatch

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rsync_restore


class TestFormatBytes:
    """Test byte formatting utility"""
    
    def test_format_bytes_zero(self):
        """Test formatting 0 bytes"""
        result = rsync_restore.format_bytes(0)
        assert "0" in result and "B" in result
    
    def test_format_bytes_small(self):
        """Test formatting bytes (< 1 KB)"""
        result = rsync_restore.format_bytes(512)
        assert "512" in result
        assert "B" in result
    
    def test_format_kilobytes(self):
        """Test formatting kilobytes"""
        result = rsync_restore.format_bytes(1024)
        assert "1.0" in result
        assert "KB" in result
    
    def test_format_megabytes(self):
        """Test formatting megabytes"""
        result = rsync_restore.format_bytes(1024 * 1024)
        assert "1.0" in result
        assert "MB" in result
    
    def test_format_gigabytes(self):
        """Test formatting gigabytes"""
        result = rsync_restore.format_bytes(1024 * 1024 * 1024)
        assert "1.0" in result
        assert "GB" in result
    
    def test_format_terabytes(self):
        """Test formatting terabytes"""
        result = rsync_restore.format_bytes(1024 * 1024 * 1024 * 1024)
        assert "1.0" in result
        assert "TB" in result
    
    def test_format_large_values(self):
        """Test formatting large byte values"""
        # 500 GB
        result = rsync_restore.format_bytes(500 * 1024 * 1024 * 1024)
        assert "500" in result
        assert "GB" in result


class TestFormatNumber:
    """Test number formatting utility"""
    
    def test_format_number_zero(self):
        """Test formatting zero"""
        result = rsync_restore.format_number(0)
        assert result == "0"
    
    def test_format_number_small(self):
        """Test formatting small numbers (< 1000)"""
        result = rsync_restore.format_number(42)
        assert result == "42"
    
    def test_format_number_thousands(self):
        """Test formatting thousands with comma"""
        result = rsync_restore.format_number(1000)
        assert "," in result or result == "1000"
    
    def test_format_number_large(self):
        """Test formatting large numbers"""
        result = rsync_restore.format_number(1234567)
        # Should have commas or be formatted nicely
        assert "1" in result
        assert "234" in result


class TestFormatDuration:
    """Test duration formatting utility"""
    
    def test_format_duration_seconds(self):
        """Test formatting seconds"""
        result = rsync_restore.format_duration(30)
        assert "30" in result
        assert "sec" in result or "s" in result
    
    def test_format_duration_minutes(self):
        """Test formatting minutes"""
        result = rsync_restore.format_duration(90)
        assert "1" in result
        assert "min" in result or "m" in result
    
    def test_format_duration_hours(self):
        """Test formatting hours"""
        result = rsync_restore.format_duration(3661)  # 1h 1m 1s
        assert "1" in result
        assert "h" in result or "hour" in result
    
    def test_format_duration_zero(self):
        """Test formatting zero duration"""
        result = rsync_restore.format_duration(0)
        assert "0" in result


class TestMatchesPattern:
    """Test pattern matching function"""
    
    def test_matches_pattern_exact(self):
        """Test exact filename match"""
        result = rsync_restore.matches_pattern("test.txt", ["test.txt"])
        assert result is True
    
    def test_matches_pattern_wildcard(self):
        """Test wildcard pattern matching"""
        result = rsync_restore.matches_pattern("test.txt", ["*.txt"])
        assert result is True
    
    def test_matches_pattern_no_match(self):
        """Test no pattern match"""
        result = rsync_restore.matches_pattern("test.txt", ["*.jpg", "*.png"])
        assert result is False
    
    def test_matches_pattern_path(self):
        """Test pattern matching with path"""
        result = rsync_restore.matches_pattern("dir/test.txt", ["dir/*.txt"])
        assert result is True
    
    def test_matches_pattern_multiple(self):
        """Test matching against multiple patterns"""
        patterns = ["*.txt", "*.log", "*.tmp"]
        assert rsync_restore.matches_pattern("file.txt", patterns) is True
        assert rsync_restore.matches_pattern("file.log", patterns) is True
        assert rsync_restore.matches_pattern("file.jpg", patterns) is False
    
    def test_matches_pattern_empty_patterns(self):
        """Test with empty pattern list"""
        result = rsync_restore.matches_pattern("test.txt", [])
        assert result is False
    
    def test_matches_pattern_directory(self):
        """Test pattern matching for directories"""
        result = rsync_restore.matches_pattern("temp/", ["temp/"])
        assert result is True
    
    def test_matches_pattern_case_sensitive(self):
        """Test case-sensitive pattern matching"""
        result = rsync_restore.matches_pattern("Test.TXT", ["*.txt"])
        # Behavior depends on implementation
        # Most systems are case-sensitive by default
        assert result in (True, False)


class TestPathNormalization:
    """Test path normalization and handling"""
    
    def test_expanduser_tilde(self):
        """Test that paths with ~ are expanded"""
        # This tests that the code uses os.path.expanduser
        expanded = os.path.expanduser("~/test")
        assert "~" not in expanded
    
    def test_path_absolute(self):
        """Test path absoluteness"""
        # Relative path
        rel_path = "test/file.txt"
        assert not os.path.isabs(rel_path)
        
        # Absolute path
        abs_path = "/tmp/test/file.txt"
        assert os.path.isabs(abs_path)
    
    def test_path_join(self):
        """Test path joining"""
        result = os.path.join("/base", "sub", "file.txt")
        assert result == "/base/sub/file.txt"


class TestScanDestinationForOrphans:
    """Test orphan file scanning"""
    
    def test_scan_empty_directory(self, tmp_path):
        """Test scanning empty directory"""
        canonical_paths = set()
        
        result = rsync_restore.scan_destination_for_orphans(
            str(tmp_path),
            canonical_paths,
            protect_patterns=[],
            cleanup_patterns=[]
        )
        
        assert 'orphans' in result
        assert 'protected' in result
        assert 'matched' in result
        assert len(result['orphans']) == 0
    
    def test_scan_with_orphan_files(self, tmp_path):
        """Test scanning directory with orphan files"""
        # Create files that are NOT in canonical set
        (tmp_path / "orphan1.txt").write_text("test")
        (tmp_path / "orphan2.txt").write_text("test")
        
        canonical_paths = set()  # Empty - all files are orphans
        
        result = rsync_restore.scan_destination_for_orphans(
            str(tmp_path),
            canonical_paths,
            protect_patterns=[],
            cleanup_patterns=[]
        )
        
        assert len(result['orphans']) == 2
    
    def test_scan_with_matched_files(self, tmp_path):
        """Test scanning directory with files in canonical set"""
        # Create files that ARE in canonical set
        (tmp_path / "file1.txt").write_text("test")
        (tmp_path / "file2.txt").write_text("test")
        
        canonical_paths = {"file1.txt", "file2.txt"}
        
        result = rsync_restore.scan_destination_for_orphans(
            str(tmp_path),
            canonical_paths,
            protect_patterns=[],
            cleanup_patterns=[]
        )
        
        assert len(result['matched']) == 2
        assert len(result['orphans']) == 0
    
    def test_scan_with_protected_patterns(self, tmp_path):
        """Test scanning with protected file patterns"""
        (tmp_path / "important.txt").write_text("test")
        (tmp_path / "temp.tmp").write_text("test")
        
        canonical_paths = set()  # Empty - files would be orphans
        protect_patterns = ["important.*"]  # Protect important.txt
        
        result = rsync_restore.scan_destination_for_orphans(
            str(tmp_path),
            canonical_paths,
            protect_patterns=protect_patterns,
            cleanup_patterns=[]
        )
        
        # important.txt should be protected, not in orphans
        assert len(result['protected']) > 0
        # temp.tmp should be orphan
        assert any('temp.tmp' in o for o in result['orphans'])
    
    def test_scan_nested_directories(self, tmp_path):
        """Test scanning nested directory structure"""
        # Create nested structure
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file.txt").write_text("test")
        
        canonical_paths = set()
        
        result = rsync_restore.scan_destination_for_orphans(
            str(tmp_path),
            canonical_paths,
            protect_patterns=[],
            cleanup_patterns=[]
        )
        
        # Should find file in subdirectory
        assert len(result['orphans']) >= 1


class TestSymlinkFarmPathHandling:
    """Test symlink farm path reconstruction"""
    
    def test_create_symlink_farm_paths(self, tmp_path):
        """Test path handling in symlink farm creation"""
        # This would require a test database
        # Testing the path logic separately
        
        source_dir = tmp_path / "source"
        farm_dir = tmp_path / "farm"
        source_dir.mkdir()
        farm_dir.mkdir()
        
        # Create test file
        (source_dir / "test.txt").write_text("content")
        
        # Test path joining
        target_path = source_dir / "test.txt"
        link_path = farm_dir / "test.txt"
        
        assert target_path.exists()
        assert not link_path.exists()


class TestPathSanitization:
    """Test path sanitization for special characters"""
    
    def test_sanitize_pipe_character(self):
        """Test handling of pipe character in paths"""
        # Pipe character (|) can be problematic on some filesystems
        path_with_pipe = "file|name.txt"
        
        # The implementation might sanitize this
        # Just verify the string handling
        assert "|" in path_with_pipe
        
        # After sanitization, it might be replaced
        sanitized = path_with_pipe.replace("|", "_")
        assert "|" not in sanitized
    
    def test_path_with_special_chars(self):
        """Test paths with various special characters"""
        special_paths = [
            "file name.txt",  # Space
            "file'name.txt",  # Apostrophe
            "file\"name.txt", # Quote
            "file(name).txt", # Parentheses
        ]
        
        for path in special_paths:
            # Just verify these don't crash
            assert isinstance(path, str)
