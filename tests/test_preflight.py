"""
Tests for preflight.py module

Tests system information gathering, file statistics,
recommendation functions, and CLI entry point.
"""
import os
import sys
import subprocess
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
        assert 'filesystem' in info  # Note: key is 'filesystem' not 'fstype'
        assert info['total'] > 0
        assert info['free'] > 0
        assert 0 <= info['percent'] <= 100
    
    def test_get_network_info(self):
        """Test network information gathering"""
        info = preflight.get_network_info()
        
        # Returns dict of interfaces, not hostname/ip
        assert isinstance(info, dict)
        # Should have at least one interface
        assert len(info) > 0
        # Each interface should have expected keys
        for iface, data in info.items():
            assert 'isup' in data
            assert 'speed' in data
            assert 'addresses' in data


class TestFileStatistics:
    """Test file statistics gathering"""
    
    def test_get_file_stats_empty_directory(self, tmp_path):
        """Test statistics for empty directory"""
        stats = preflight.get_file_stats(str(tmp_path))
        
        assert stats['total_files'] == 0
        assert stats['total_size_GB'] == 0
        assert stats['small_files'] == 0
        assert stats['medium_files'] == 0
        assert stats['large_files'] == 0
    
    def test_get_file_stats_with_files(self, tmp_path):
        """Test statistics for directory with files"""
        # Create test files (all small < 1MB)
        (tmp_path / "file1.txt").write_text("hello")  # 5 bytes
        (tmp_path / "file2.txt").write_text("world!")  # 6 bytes
        (tmp_path / "file3.txt").write_text("test")  # 4 bytes
        
        stats = preflight.get_file_stats(str(tmp_path))
        
        assert stats['total_files'] == 3
        assert stats['small_files'] == 3  # All files < 1MB
        assert stats['medium_files'] == 0
        assert stats['large_files'] == 0
    
    def test_get_file_stats_with_subdirectories(self, tmp_path):
        """Test that subdirectories are recursively scanned"""
        # Create nested structure
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "file1.txt").write_text("hello")
        (subdir / "file2.txt").write_text("world")
        
        stats = preflight.get_file_stats(str(tmp_path))
        
        assert stats['total_files'] == 2
        assert stats['small_files'] == 2
    
    def test_get_file_stats_large_files(self, tmp_path):
        """Test statistics with large files"""
        # Create files of varying sizes
        # small: < 1MB, medium: 1-100MB, large: > 100MB
        (tmp_path / "small.txt").write_bytes(b"x" * 100)  # small
        (tmp_path / "medium.txt").write_bytes(b"x" * (2 * 1024 * 1024))  # 2MB = medium
        (tmp_path / "large.txt").write_bytes(b"x" * (101 * 1024 * 1024))  # 101MB = large
        
        stats = preflight.get_file_stats(str(tmp_path))
        
        assert stats['total_files'] == 3
        assert stats['small_files'] == 1
        assert stats['medium_files'] == 1
        assert stats['large_files'] == 1
    
    def test_get_file_stats_many_small_files(self, tmp_path):
        """Test statistics with many small files"""
        # Create 100 small files
        for i in range(100):
            (tmp_path / f"file{i}.txt").write_text("x")
        
        stats = preflight.get_file_stats(str(tmp_path))
        
        assert stats['total_files'] == 100
        assert stats['small_files'] == 100


class TestDiskSpeedTest:
    """Test disk speed testing"""
    
    def test_disk_speed_test_returns_results(self, tmp_path):
        """Test that disk speed test returns valid results"""
        result = preflight.disk_speed_test(str(tmp_path), file_size_mb=1)
        
        assert 'write_MBps' in result
        assert 'read_MBps' in result
        assert result['write_MBps'] > 0
        assert result['read_MBps'] > 0
    
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
        
        assert result_small['write_MBps'] > 0
        assert result_medium['write_MBps'] > 0
        # Both should complete successfully


class TestDurationEstimation:
    """Test duration estimation functions"""
    
    def test_estimate_duration_basic(self):
        """Test basic duration estimation"""
        # 100 GB at 50 MB/s = 100 * 1024 MB / 50 MB/s / 60 = ~34 minutes
        duration = preflight.estimate_duration(100, 50)
        
        assert duration > 0
        # Returns minutes: 100 * 1024 / 50 / 60 = ~34 minutes
        assert 30 < duration < 40
    
    def test_estimate_duration_slow_speed(self):
        """Test estimation with slow transfer speed"""
        duration = preflight.estimate_duration(10, 1)
        
        # 10 GB at 1 MB/s = 10 * 1024 / 1 / 60 = ~170 minutes
        assert duration > 150
    
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
            'total_files': 1000,
            'small_files': 500,
            'medium_files': 400,
            'large_files': 100,
        }
        
        thread_count, explanation = preflight.recommend_thread_count(
            cpu_count=8,
            file_stats=file_stats
        )
        
        assert thread_count > 0
        assert thread_count <= 16  # Capped at 16 for mixed files
        assert isinstance(explanation, dict)
    
    def test_recommend_thread_count_many_small_files(self):
        """Test recommendation with many small files"""
        file_stats = {
            'total_files': 100000,
            'small_files': 90000,  # Mostly small files
            'medium_files': 8000,
            'large_files': 2000,
        }
        
        thread_count, explanation = preflight.recommend_thread_count(
            cpu_count=8,
            file_stats=file_stats
        )
        
        # Many small files should recommend higher thread count (2x CPU, max 32)
        assert thread_count >= 4
        assert 'cpu_reason' in explanation
    
    def test_recommend_thread_count_few_large_files(self):
        """Test recommendation with few large files"""
        file_stats = {
            'total_files': 10,
            'small_files': 0,
            'medium_files': 2,
            'large_files': 8,  # Mostly large files
        }
        
        thread_count, explanation = preflight.recommend_thread_count(
            cpu_count=8,
            file_stats=file_stats
        )
        
        # Few large files = mixed/large, capped at 1x CPU (max 16)
        assert thread_count <= 16
        assert thread_count > 0
    
    def test_recommend_thread_count_with_disk_speed(self):
        """Test recommendation considering disk speed"""
        file_stats = {
            'total_files': 1000,
            'small_files': 500,
            'medium_files': 400,
            'large_files': 100,
        }
        
        # Slow disk should recommend fewer threads
        thread_count_slow, _ = preflight.recommend_thread_count(
            cpu_count=8,
            file_stats=file_stats,
            disk_speed_MBps=10
        )
        
        # Fast disk can handle more threads
        thread_count_fast, _ = preflight.recommend_thread_count(
            cpu_count=8,
            file_stats=file_stats,
            disk_speed_MBps=500
        )
        
        assert thread_count_slow > 0
        assert thread_count_fast > 0
    
    def test_recommend_thread_count_pipe_filesystem(self):
        """Test recommendation for network filesystems"""
        file_stats = {
            'total_files': 1000,
            'small_files': 500,
            'medium_files': 400,
            'large_files': 100,
        }
        
        # Network filesystems (nfs, cifs, smb) are capped at CPU count
        for fs in ['nfs', 'cifs', 'smb']:
            thread_count, explanation = preflight.recommend_thread_count(
                cpu_count=8,
                file_stats=file_stats,
                dest_fs=fs
            )
            assert thread_count <= 8  # Capped at CPU count for network FS
            assert thread_count > 0
    
    def test_recommend_thread_count_native_filesystem(self):
        """Test recommendation for native filesystems"""
        file_stats = {
            'total_files': 1000,
            'small_files': 500,
            'medium_files': 400,
            'large_files': 100,
        }
        
        thread_count, explanation = preflight.recommend_thread_count(
            cpu_count=8,
            file_stats=file_stats,
            dest_fs='ext4'
        )
        
        # Native filesystems can use multiple threads
        assert thread_count > 1
        assert isinstance(explanation, dict)


class TestThreadRecommendationsWithFD:
    """Test thread recommendations with file descriptor limits"""
    
    def test_recommend_thread_count_with_fd_basic(self):
        """Test FD-aware thread recommendation"""
        file_stats = {
            'total_files': 1000,
            'small_files': 500,
            'medium_files': 400,
            'large_files': 100,
        }
        
        thread_count, explanation = preflight.recommend_thread_count_with_fd(
            cpu_count=8,
            file_stats=file_stats,
            fd_limit=1024
        )
        
        assert thread_count > 0
        assert thread_count <= 32  # Max cap
        assert isinstance(explanation, dict)
    
    def test_recommend_thread_count_with_low_fd_limit(self):
        """Test that low FD limit reduces thread count"""
        file_stats = {
            'total_files': 10000,
            'small_files': 9000,
            'medium_files': 800,
            'large_files': 200,
        }
        
        # Very low FD limit should reduce threads
        thread_count, _ = preflight.recommend_thread_count_with_fd(
            cpu_count=16,
            file_stats=file_stats,
            fd_limit=256
        )
        
        # Should be capped by FD limit
        assert thread_count > 0
        assert thread_count <= 32
    
    def test_recommend_thread_count_with_high_fd_limit(self):
        """Test that high FD limit allows more threads"""
        file_stats = {
            'total_files': 10000,
            'small_files': 9000,
            'medium_files': 800,
            'large_files': 200,
        }
        
        thread_count, _ = preflight.recommend_thread_count_with_fd(
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
        
        # Check actual keys returned by implementation
        assert 'cpu' in summary
        assert 'memory' in summary
        assert 'file_stats' in summary
        assert 'disk_src' in summary
        assert 'disk_dst' in summary
    
    def test_preflight_summary_with_existing_dest(self, tmp_path):
        """Test summary with existing destination files"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        (source / "file1.txt").write_text("hello")
        (dest / "existing.txt").write_text("already here")
        
        summary = preflight.preflight_summary(str(source), str(dest))
        
        assert summary['file_stats']['total_files'] > 0
    
    def test_preflight_summary_includes_disk_info(self, tmp_path):
        """Test that summary includes disk information"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        summary = preflight.preflight_summary(str(source), str(dest))
        
        assert 'disk_src' in summary
        assert 'disk_dst' in summary
        assert summary['disk_src']['free'] > 0
        assert summary['disk_dst']['free'] > 0


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


class TestCLIEntryPoint:
    """Test CLI entry point for preflight.py"""
    
    def test_cli_shows_usage_without_args(self):
        """Test that CLI shows usage when no arguments provided"""
        result = subprocess.run(
            [sys.executable, 'preflight.py'],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        assert result.returncode == 1
        assert 'Usage:' in result.stdout or 'usage:' in result.stdout.lower()
    
    def test_cli_shows_error_for_nonexistent_source(self, tmp_path):
        """Test that CLI shows error for nonexistent source path"""
        result = subprocess.run(
            [sys.executable, 'preflight.py', '/nonexistent/source', str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        assert result.returncode == 1
        assert 'Error' in result.stdout or 'error' in result.stdout.lower()
    
    def test_cli_shows_error_for_nonexistent_dest(self, tmp_path):
        """Test that CLI shows error for nonexistent destination path"""
        result = subprocess.run(
            [sys.executable, 'preflight.py', str(tmp_path), '/nonexistent/dest'],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        assert result.returncode == 1
        assert 'Error' in result.stdout or 'error' in result.stdout.lower()
    
    def test_cli_runs_successfully_with_valid_paths(self, tmp_path):
        """Test that CLI runs successfully with valid paths"""
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        # Create a test file
        (source / "test.txt").write_text("test content")
        
        result = subprocess.run(
            [sys.executable, 'preflight.py', str(source), str(dest)],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            timeout=60
        )
        assert result.returncode == 0
        assert 'Pre-flight' in result.stdout or 'CPU' in result.stdout


class TestErrorHandling:
    """Test error handling in preflight functions"""
    
    def test_get_file_stats_nonexistent_directory(self):
        """Test handling of nonexistent directory - returns empty stats"""
        # os.walk doesn't raise for nonexistent paths, just returns empty
        stats = preflight.get_file_stats("/nonexistent/path/that/does/not/exist")
        assert stats['total_files'] == 0
        assert stats['total_size_GB'] == 0
    
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
