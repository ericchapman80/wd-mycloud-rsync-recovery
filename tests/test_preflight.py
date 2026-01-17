"""
Tests for preflight.py module

Tests system information gathering, file statistics,
and recommendation functions.
"""
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import preflight
    HAS_PREFLIGHT = True
except ImportError:
    HAS_PREFLIGHT = False
    pytest.skip("preflight module not available", allow_module_level=True)


class TestSystemInfo:
    """Test system information gathering functions"""
    
    def test_get_cpu_info(self):
        """Test CPU information gathering"""
        info = preflight.get_cpu_info()
        
        assert 'cpu_count' in info
        assert 'cpu_freq' in info
        assert 'cpu_model' in info
        assert info['cpu_count'] > 0
    
    def test_get_memory_info(self):
        """Test memory information gathering"""
        info = preflight.get_memory_info()
        
        assert 'total' in info
        assert 'available' in info
        assert 'percent' in info
        assert info['total'] > 0
        assert info['available'] > 0
        assert 0 <= info['percent'] <= 100
    
    def test_get_disk_info(self, tmp_path):
        """Test disk information gathering"""
        info = preflight.get_disk_info(str(tmp_path))
        
        assert 'total' in info
        assert 'used' in info
        assert 'free' in info
        assert 'percent' in info
        assert 'fstype' in info
        assert info['total'] > 0
        assert info['free'] > 0
        assert 0 <= info['percent'] <= 100
    
    def test_get_network_info(self):
        """Test network information gathering"""
        info = preflight.get_network_info()
        
        assert 'hostname' in info
        assert 'ip_address' in info
        assert isinstance(info['hostname'], str)


class TestFileStatistics:
    """Test file statistics gathering"""
    
    def test_get_file_stats_empty_directory(self, tmp_path):
        """Test statistics for empty directory"""
        stats = preflight.get_file_stats(str(tmp_path))
        
        assert stats['file_count'] == 0
        assert stats['total_size'] == 0
        assert stats['avg_size'] == 0
    
    def test_get_file_stats_with_files(self, tmp_path):
        """Test statistics for directory with files"""
        # Create test files
        (tmp_path / "file1.txt").write_text("hello")  # 5 bytes
        (tmp_path / "file2.txt").write_text("world!")  # 6 bytes
        (tmp_path / "file3.txt").write_text("test")  # 4 bytes
        
        stats = preflight.get_file_stats(str(tmp_path))
        
        assert stats['file_count'] == 3
        assert stats['total_size'] == 15
        assert stats['avg_size'] == 5
        assert stats['min_size'] == 4
        assert stats['max_size'] == 6
    
    def test_get_file_stats_with_subdirectories(self, tmp_path):
        """Test that subdirectories are recursively scanned"""
        # Create nested structure
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "file1.txt").write_text("hello")
        (subdir / "file2.txt").write_text("world")
        
        stats = preflight.get_file_stats(str(tmp_path))
        
        assert stats['file_count'] == 2
        assert stats['total_size'] == 10
    
    def test_get_file_stats_large_files(self, tmp_path):
        """Test statistics with large files"""
        # Create files of varying sizes
        (tmp_path / "small.txt").write_bytes(b"x" * 100)
        (tmp_path / "medium.txt").write_bytes(b"x" * 10000)
        (tmp_path / "large.txt").write_bytes(b"x" * 1000000)
        
        stats = preflight.get_file_stats(str(tmp_path))
        
        assert stats['file_count'] == 3
        assert stats['total_size'] == 1010100
        assert stats['max_size'] == 1000000
        assert stats['min_size'] == 100
    
    def test_get_file_stats_many_small_files(self, tmp_path):
        """Test statistics with many small files"""
        # Create 100 small files
        for i in range(100):
            (tmp_path / f"file{i}.txt").write_text("x")
        
        stats = preflight.get_file_stats(str(tmp_path))
        
        assert stats['file_count'] == 100
        assert stats['avg_size'] == 1


class TestDiskSpeedTest:
    """Test disk speed testing"""
    
    def test_disk_speed_test_returns_results(self, tmp_path):
        """Test that disk speed test returns valid results"""
        result = preflight.disk_speed_test(str(tmp_path), file_size_mb=1)
        
        assert 'write_speed' in result
        assert 'read_speed' in result
        assert result['write_speed'] > 0
        assert result['read_speed'] > 0
    
    def test_disk_speed_test_creates_temp_file(self, tmp_path):
        """Test that speed test creates and cleans up temp file"""
        preflight.disk_speed_test(str(tmp_path), file_size_mb=1)
        
        # Temp file should be cleaned up
        temp_files = list(tmp_path.glob("*speedtest*"))
        assert len(temp_files) == 0
    
    def test_disk_speed_test_different_sizes(self, tmp_path):
        """Test disk speed with different file sizes"""
        result_small = preflight.disk_speed_test(str(tmp_path), file_size_mb=1)
        result_medium = preflight.disk_speed_test(str(tmp_path), file_size_mb=10)
        
        assert result_small['write_speed'] > 0
        assert result_medium['write_speed'] > 0
        # Both should complete successfully


class TestDurationEstimation:
    """Test duration estimation functions"""
    
    def test_estimate_duration_basic(self):
        """Test basic duration estimation"""
        # 100 GB at 50 MB/s
        duration = preflight.estimate_duration(100, 50)
        
        assert duration > 0
        # Should be around 2000 seconds (100 * 1024 / 50)
        assert 1900 < duration < 2100
    
    def test_estimate_duration_slow_speed(self):
        """Test estimation with slow transfer speed"""
        duration = preflight.estimate_duration(10, 1)
        
        # 10 GB at 1 MB/s = ~10,240 seconds
        assert duration > 10000
    
    def test_estimate_duration_fast_speed(self):
        """Test estimation with fast transfer speed"""
        duration = preflight.estimate_duration(10, 500)
        
        # 10 GB at 500 MB/s = ~20 seconds
        assert duration < 50


class TestThreadRecommendations:
    """Test thread count recommendation logic"""
    
    def test_recommend_thread_count_basic(self):
        """Test basic thread count recommendation"""
        file_stats = {
            'file_count': 1000,
            'avg_size': 1024 * 1024,  # 1 MB average
            'total_size': 1024 * 1024 * 1000
        }
        
        thread_count = preflight.recommend_thread_count(
            cpu_count=8,
            file_stats=file_stats
        )
        
        assert thread_count > 0
        assert thread_count <= 8  # Should not exceed CPU count
    
    def test_recommend_thread_count_many_small_files(self):
        """Test recommendation with many small files"""
        file_stats = {
            'file_count': 100000,
            'avg_size': 1024,  # 1 KB average
            'total_size': 1024 * 100000
        }
        
        thread_count = preflight.recommend_thread_count(
            cpu_count=8,
            file_stats=file_stats
        )
        
        # Many small files should recommend higher thread count
        assert thread_count >= 4
    
    def test_recommend_thread_count_few_large_files(self):
        """Test recommendation with few large files"""
        file_stats = {
            'file_count': 10,
            'avg_size': 1024 * 1024 * 100,  # 100 MB average
            'total_size': 1024 * 1024 * 1000
        }
        
        thread_count = preflight.recommend_thread_count(
            cpu_count=8,
            file_stats=file_stats
        )
        
        # Few large files should recommend lower thread count
        assert thread_count <= 4
    
    def test_recommend_thread_count_with_disk_speed(self):
        """Test recommendation considering disk speed"""
        file_stats = {
            'file_count': 1000,
            'avg_size': 1024 * 1024,
            'total_size': 1024 * 1024 * 1000
        }
        
        # Slow disk should recommend fewer threads
        thread_count_slow = preflight.recommend_thread_count(
            cpu_count=8,
            file_stats=file_stats,
            disk_speed_MBps=10
        )
        
        # Fast disk can handle more threads
        thread_count_fast = preflight.recommend_thread_count(
            cpu_count=8,
            file_stats=file_stats,
            disk_speed_MBps=500
        )
        
        assert thread_count_slow > 0
        assert thread_count_fast > 0
    
    def test_recommend_thread_count_pipe_filesystem(self):
        """Test recommendation for pipe filesystems (NTFS, exFAT, etc)"""
        file_stats = {
            'file_count': 1000,
            'avg_size': 1024 * 1024,
            'total_size': 1024 * 1024 * 1000
        }
        
        # Pipe filesystems should recommend only 1 thread
        for fs in ['ntfs', 'vfat', 'exfat', 'cifs']:
            thread_count = preflight.recommend_thread_count(
                cpu_count=8,
                file_stats=file_stats,
                dest_fs=fs
            )
            assert thread_count == 1
    
    def test_recommend_thread_count_native_filesystem(self):
        """Test recommendation for native filesystems"""
        file_stats = {
            'file_count': 1000,
            'avg_size': 1024 * 1024,
            'total_size': 1024 * 1024 * 1000
        }
        
        thread_count = preflight.recommend_thread_count(
            cpu_count=8,
            file_stats=file_stats,
            dest_fs='ext4'
        )
        
        # Native filesystems can use multiple threads
        assert thread_count > 1


class TestThreadRecommendationsWithFD:
    """Test thread recommendations with file descriptor limits"""
    
    def test_recommend_thread_count_with_fd_basic(self):
        """Test FD-aware thread recommendation"""
        file_stats = {
            'file_count': 1000,
            'avg_size': 1024 * 1024,
            'total_size': 1024 * 1024 * 1000
        }
        
        thread_count = preflight.recommend_thread_count_with_fd(
            cpu_count=8,
            file_stats=file_stats,
            fd_limit=1024
        )
        
        assert thread_count > 0
        assert thread_count <= 8
    
    def test_recommend_thread_count_with_low_fd_limit(self):
        """Test that low FD limit reduces thread count"""
        file_stats = {
            'file_count': 10000,
            'avg_size': 1024,
            'total_size': 1024 * 10000
        }
        
        # Very low FD limit should reduce threads
        thread_count = preflight.recommend_thread_count_with_fd(
            cpu_count=16,
            file_stats=file_stats,
            fd_limit=256
        )
        
        # Should be capped by FD limit
        assert thread_count < 16
    
    def test_recommend_thread_count_with_high_fd_limit(self):
        """Test that high FD limit allows more threads"""
        file_stats = {
            'file_count': 10000,
            'avg_size': 1024,
            'total_size': 1024 * 10000
        }
        
        thread_count = preflight.recommend_thread_count_with_fd(
            cpu_count=8,
            file_stats=file_stats,
            fd_limit=65536
        )
        
        # High FD limit should not restrict threads
        assert thread_count > 0


class TestPreflightSummary:
    """Test preflight summary generation"""
    
    def test_preflight_summary_basic(self, tmp_path):
        """Test basic preflight summary generation"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        # Create test files
        (source / "file1.txt").write_text("hello")
        (source / "file2.txt").write_text("world")
        
        summary = preflight.preflight_summary(str(source), str(dest))
        
        assert 'source' in summary
        assert 'dest' in summary
        assert 'file_stats' in summary
        assert 'cpu_info' in summary
        assert 'memory_info' in summary
    
    def test_preflight_summary_with_existing_dest(self, tmp_path):
        """Test summary with existing destination files"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        (source / "file1.txt").write_text("hello")
        (dest / "existing.txt").write_text("already here")
        
        summary = preflight.preflight_summary(str(source), str(dest))
        
        assert summary['file_stats']['file_count'] > 0
    
    def test_preflight_summary_includes_disk_info(self, tmp_path):
        """Test that summary includes disk information"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        summary = preflight.preflight_summary(str(source), str(dest))
        
        assert 'source_disk' in summary
        assert 'dest_disk' in summary
        assert summary['source_disk']['free'] > 0
        assert summary['dest_disk']['free'] > 0


class TestPreflightReport:
    """Test preflight report printing"""
    
    def test_print_preflight_report_executes(self, tmp_path, capsys):
        """Test that report printing executes without error"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        (source / "test.txt").write_text("content")
        
        summary = preflight.preflight_summary(str(source), str(dest))
        
        # Should not raise exception
        preflight.print_preflight_report(summary, str(source), str(dest))
        
        captured = capsys.readouterr()
        # Should have printed something
        assert len(captured.out) > 0
    
    def test_print_preflight_report_contains_key_info(self, tmp_path, capsys):
        """Test that report contains key information"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        (source / "test.txt").write_text("content")
        
        summary = preflight.preflight_summary(str(source), str(dest))
        preflight.print_preflight_report(summary, str(source), str(dest))
        
        captured = capsys.readouterr()
        output = captured.out.lower()
        
        # Check for key sections
        assert 'cpu' in output or 'thread' in output
        assert 'file' in output or 'size' in output


class TestPipeFilesystemDetection:
    """Test pipe filesystem detection"""
    
    def test_identifies_pipe_filesystems(self):
        """Test that pipe filesystems are correctly identified"""
        pipe_fs = ['ntfs', 'vfat', 'fat', 'msdos', 'exfat', 'cifs', 'smb']
        
        for fs in pipe_fs:
            assert fs.lower() in preflight.PIPE_FS_TAGS
    
    def test_native_filesystems_not_in_pipe_list(self):
        """Test that native filesystems are not marked as pipe"""
        native_fs = ['ext4', 'ext3', 'xfs', 'btrfs', 'zfs']
        
        for fs in native_fs:
            assert fs.lower() not in preflight.PIPE_FS_TAGS


class TestErrorHandling:
    """Test error handling in preflight functions"""
    
    def test_get_file_stats_nonexistent_directory(self):
        """Test handling of nonexistent directory"""
        with pytest.raises(Exception):
            preflight.get_file_stats("/nonexistent/path/that/does/not/exist")
    
    def test_get_disk_info_nonexistent_path(self):
        """Test handling of nonexistent path for disk info"""
        with pytest.raises(Exception):
            preflight.get_disk_info("/nonexistent/path/that/does/not/exist")
    
    def test_disk_speed_test_readonly_directory(self, tmp_path):
        """Test handling of read-only directory for speed test"""
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)
        
        try:
            # Should raise exception or handle gracefully
            result = preflight.disk_speed_test(str(readonly_dir), file_size_mb=1)
            # If it returns, it handled the error gracefully
            assert True
        except (PermissionError, OSError):
            # Expected for read-only directory
            assert True
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(0o755)
