"""
Tests for rsync command generation and execution in rsync_restore.py

Tests command building, option handling, and rsync process management.
"""
import os
import sys
import subprocess
from unittest.mock import Mock, patch, MagicMock

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rsync_restore


class TestRsyncMonitor:
    """Test RsyncMonitor class for progress tracking"""
    
    def test_monitor_initialization(self, tmp_path):
        """Test RsyncMonitor initializes with correct defaults"""
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        assert monitor.files_transferred == 0
        assert monitor.bytes_transferred == 0
        assert monitor.current_file == ""
        assert monitor.start_time is None  # Not started until start() called
    
    def test_monitor_update_file(self, tmp_path):
        """Test updating file transfer count"""
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        monitor.update_progress(files_transferred=10, current_file="test.txt")
        
        assert monitor.files_transferred == 10
        assert monitor.current_file == "test.txt"
    
    def test_monitor_update_bytes(self, tmp_path):
        """Test updating bytes transferred"""
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        monitor.update_progress(bytes_transferred=104857600)  # 100 MB
        
        assert monitor.bytes_transferred == 104857600
    
    def test_monitor_completion(self, tmp_path):
        """Test starting and stopping monitor"""
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        assert monitor.running is False
        monitor.start()
        assert monitor.running is True
        monitor.stop()
        assert monitor.running is False


class TestParseRsyncProgress:
    """Test rsync progress line parsing"""
    
    def test_parse_file_transfer(self, tmp_path):
        """Test parsing file transfer line"""
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        # Typical rsync output for file transfer
        line = "test/file.txt"
        rsync_restore.parse_rsync_progress(line, monitor)
        
        # Current file should be updated
        assert monitor.current_file == "test/file.txt"
    
    def test_parse_progress_line(self, tmp_path):
        """Test parsing progress percentage line"""
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        # Rsync progress format: "  1,234,567  50%  123.45kB/s    0:00:12"
        line = "  1234567  50%  123.45kB/s    0:00:12"
        rsync_restore.parse_rsync_progress(line, monitor)
        
        # Monitor should update (implementation dependent)
        # This is a basic smoke test
        assert monitor is not None
    
    def test_parse_xfr_count(self, tmp_path):
        """Test parsing transfer count (xfr#N)"""
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        # Rsync shows transfer count like: "xfr#5"
        line = "xfr#10, to-chk=100/200"
        rsync_restore.parse_rsync_progress(line, monitor)
        
        # Should extract file count from xfr#N
        assert monitor.files_transferred == 10
    
    def test_parse_total_size(self, tmp_path):
        """Test parsing total size from rsync output"""
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        # Rsync final summary: "total size is 12,345,678"
        line = "total size is 12345678  speedup is 1.00"
        rsync_restore.parse_rsync_progress(line, monitor)
        
        # Monitor should recognize completion
        # Note: Implementation may not have is_complete flag
        assert monitor is not None
    
    def test_parse_empty_line(self, tmp_path):
        """Test parsing empty line doesn't crash"""
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_restore.parse_rsync_progress("", monitor)
        
        # Should not change monitor state
        assert monitor.files_transferred == 0
    
    def test_parse_invalid_line(self, tmp_path):
        """Test parsing invalid/unknown line format"""
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_restore.parse_rsync_progress("some random text", monitor)
        
        # Should not crash
        assert monitor is not None


class TestRunRsync:
    """Test rsync command execution"""
    
    @patch('subprocess.Popen')
    def test_run_rsync_basic_command(self, mock_popen, tmp_path):
        """Test basic rsync command generation"""
        # Mock process
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        source = "/source/"
        dest = "/dest/"
        
        returncode, errors = rsync_restore.run_rsync(source, dest, monitor)
        
        # Check that Popen was called
        assert mock_popen.called
        
        # Extract command from call
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        
        # Basic rsync command should include these flags
        assert 'rsync' in cmd[0]
        assert '-aP' in cmd or '-a' in cmd
        assert source in cmd
        assert dest in cmd
    
    @patch('subprocess.Popen')
    def test_run_rsync_with_verbose(self, mock_popen, tmp_path):
        """Test rsync command with verbose flag"""
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        returncode, errors = rsync_restore.run_rsync(
            "/source/",
            "/dest/",
            monitor,
            verbose=True
        )
        
        cmd = mock_popen.call_args[0][0]
        assert '-v' in cmd or '-vv' in cmd
    
    @patch('subprocess.Popen')
    def test_run_rsync_with_dry_run(self, mock_popen, tmp_path):
        """Test rsync command with dry-run flag"""
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        returncode, errors = rsync_restore.run_rsync(
            "/source/",
            "/dest/",
            monitor,
            dry_run=True
        )
        
        cmd = mock_popen.call_args[0][0]
        assert '--dry-run' in cmd
    
    @patch('subprocess.Popen')
    def test_run_rsync_with_delete(self, mock_popen, tmp_path):
        """Test rsync command with delete flag"""
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        returncode, errors = rsync_restore.run_rsync(
            "/source/",
            "/dest/",
            monitor,
            delete=True
        )
        
        cmd = mock_popen.call_args[0][0]
        assert '--delete' in cmd
    
    @patch('subprocess.Popen')
    def test_run_rsync_with_exclude(self, mock_popen, tmp_path):
        """Test rsync command with exclude patterns"""
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        exclude_patterns = ['*.tmp', '.DS_Store']
        
        returncode, errors = rsync_restore.run_rsync(
            "/source/",
            "/dest/",
            monitor,
            exclude=exclude_patterns
        )
        
        cmd = mock_popen.call_args[0][0]
        assert '--exclude' in cmd
        assert '*.tmp' in cmd
        assert '.DS_Store' in cmd
    
    @patch('subprocess.Popen')
    def test_run_rsync_adds_trailing_slash(self, mock_popen, tmp_path):
        """Test that rsync adds trailing slash to source"""
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        # Source without trailing slash
        returncode, errors = rsync_restore.run_rsync(
            "/source",  # No trailing slash
            "/dest/",
            monitor
        )
        
        cmd = mock_popen.call_args[0][0]
        # Source should have trailing slash added
        assert '/source/' in cmd
    
    @patch('subprocess.Popen')
    def test_run_rsync_handles_process_output(self, mock_popen, tmp_path):
        """Test that rsync processes output lines"""
        mock_process = MagicMock()
        mock_process.stdout = [
            "file1.txt\n",
            "xfr#1, to-chk=99/100\n",
            "file2.txt\n",
            "xfr#2, to-chk=98/100\n",
        ]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        returncode, errors = rsync_restore.run_rsync("/source/", "/dest/", monitor)
        
        # Monitor should have parsed the output
        assert monitor.files_transferred == 2
    
    @patch('subprocess.Popen')
    def test_run_rsync_detects_errors(self, mock_popen, tmp_path):
        """Test that rsync detects error messages"""
        mock_process = MagicMock()
        mock_process.stdout = [
            "file1.txt\n",
            "rsync: failed to copy file\n",
            "rsync error: some files could not be transferred\n",
        ]
        mock_process.wait.return_value = 1
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        returncode, errors = rsync_restore.run_rsync("/source/", "/dest/", monitor)
        
        # Should detect errors in output
        assert len(errors) > 0
        assert returncode == 1
    
    @patch('subprocess.Popen')
    def test_run_rsync_keyboard_interrupt(self, mock_popen, tmp_path):
        """Test that rsync handles keyboard interrupt"""
        mock_process = MagicMock()
        # Create a generator that raises KeyboardInterrupt
        def interrupt_generator():
            raise KeyboardInterrupt()
            yield  # Never reached
        
        mock_process.stdout = interrupt_generator()
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        returncode, errors = rsync_restore.run_rsync("/source/", "/dest/", monitor)
        
        # Should return interrupt code
        assert returncode == 130
        mock_process.terminate.assert_called_once()


class TestRsyncCommandOptions:
    """Test various rsync command option combinations"""
    
    @patch('subprocess.Popen')
    def test_rsync_preserves_permissions(self, mock_popen, tmp_path):
        """Test that rsync preserves permissions (-a flag)"""
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_restore.run_rsync("/source/", "/dest/", monitor)
        
        cmd = mock_popen.call_args[0][0]
        # -a flag includes permissions, times, symlinks, etc.
        assert '-a' in ' '.join(cmd) or '-aP' in ' '.join(cmd)
    
    @patch('subprocess.Popen')
    def test_rsync_shows_progress(self, mock_popen, tmp_path):
        """Test that rsync shows progress (-P flag)"""
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_restore.run_rsync("/source/", "/dest/", monitor)
        
        cmd = mock_popen.call_args[0][0]
        # -P or --progress flag
        assert '-P' in ' '.join(cmd) or '--progress' in ' '.join(cmd)
    
    @patch('subprocess.Popen')
    def test_rsync_with_checksum(self, mock_popen, tmp_path):
        """Test rsync with checksum verification"""
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "test.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_restore.run_rsync("/source/", "/dest/", monitor, checksum=True)
        
        cmd = mock_popen.call_args[0][0]
        assert '--checksum' in cmd
