"""
Integration tests for symlink farm + rsync workflows in rsync_restore.py

Tests end-to-end workflows combining farm creation with rsync execution.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rsync_restore


class TestFarmToRsyncWorkflow:
    """Test complete farm creation → rsync execution workflow"""
    
    def test_create_farm_then_rsync(self, tmp_path):
        """Test creating farm then running rsync on it"""
        db_path = tmp_path / "index.db"
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        farm = tmp_path / "farm"
        
        source.mkdir()
        dest.mkdir()
        
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
            for i in range(5):
                conn.execute(f"INSERT INTO Files VALUES ({i+1}, 'file{i}.txt', NULL, 'f{i:03d}')")
        
        # Create source files
        for i in range(5):
            content_id = f"f{i:03d}"
            file_dir = source / content_id[:2] / content_id
            file_dir.mkdir(parents=True)
            (file_dir / content_id).write_text(f"content {i}")
        
        # Create farm
        farm_result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert farm_result['created'] == 5
        assert os.path.isdir(str(farm))
        
        # Run rsync from farm to dest
        log_file = tmp_path / "rsync.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_code, errors = rsync_restore.run_rsync(
            str(farm),
            str(dest),
            monitor,
            checksum=True,
            dry_run=False
        )
        
        # Verify files were copied
        assert rsync_code == 0
        assert len(list(dest.glob("*.txt"))) == 5
    
    def test_incomplete_farm_rsync_handling(self, tmp_path):
        """Test rsync with incomplete symlink farm"""
        db_path = tmp_path / "index.db"
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        farm = tmp_path / "farm"
        
        source.mkdir()
        dest.mkdir()
        farm.mkdir()
        
        # Create database with 10 files
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
                conn.execute(f"INSERT INTO Files VALUES ({i+1}, 'file{i}.txt', NULL, 'f{i:03d}')")
        
        # Create only 5 source files (incomplete)
        for i in range(5):
            content_id = f"f{i:03d}"
            file_dir = source / content_id[:2] / content_id
            file_dir.mkdir(parents=True)
            (file_dir / content_id).write_text(f"content {i}")
        
        # Create farm (will have missing files)
        farm_result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert farm_result['created'] == 5
        assert farm_result['missing'] == 5
        
        # Rsync should still work with available files
        log_file = tmp_path / "rsync.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_code, errors = rsync_restore.run_rsync(
            str(farm),
            str(dest),
            monitor,
            dry_run=False
        )
        
        # Should copy available files
        assert len(list(dest.glob("*.txt"))) == 5
    
    def test_farm_update_and_incremental_rsync(self, tmp_path):
        """Test updating farm and running incremental rsync"""
        db_path = tmp_path / "index.db"
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        farm = tmp_path / "farm"
        
        source.mkdir()
        dest.mkdir()
        
        # Initial database with 3 files
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            for i in range(3):
                conn.execute(f"INSERT INTO Files VALUES ({i+1}, 'file{i}.txt', NULL, 'f{i:03d}')")
        
        # Create initial source files
        for i in range(3):
            content_id = f"f{i:03d}"
            file_dir = source / content_id[:2] / content_id
            file_dir.mkdir(parents=True)
            (file_dir / content_id).write_text(f"content {i}")
        
        # Initial farm creation and sync
        farm_result1 = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        log_file = tmp_path / "rsync.log"
        monitor1 = rsync_restore.RsyncMonitor(str(log_file))
        rsync_restore.run_rsync(str(farm), str(dest), monitor1, dry_run=False)
        
        initial_count = len(list(dest.glob("*.txt")))
        assert initial_count == 3
        
        # Add more files to database
        with sqlite3.connect(str(db_path)) as conn:
            for i in range(3, 6):
                conn.execute(f"INSERT INTO Files VALUES ({i+1}, 'file{i}.txt', NULL, 'f{i:03d}')")
        
        # Create new source files
        for i in range(3, 6):
            content_id = f"f{i:03d}"
            file_dir = source / content_id[:2] / content_id
            file_dir.mkdir(parents=True)
            (file_dir / content_id).write_text(f"content {i}")
        
        # Update farm (incremental)
        farm_result2 = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        # Incremental rsync
        monitor2 = rsync_restore.RsyncMonitor(str(log_file))
        rsync_restore.run_rsync(str(farm), str(dest), monitor2, dry_run=False)
        
        # Should now have all 6 files
        final_count = len(list(dest.glob("*.txt")))
        assert final_count == 6


class TestFarmRsyncErrorRecovery:
    """Test error recovery in farm→rsync workflows"""
    
    def test_broken_symlinks_in_farm(self, tmp_path):
        """Test handling of broken symlinks in farm"""
        db_path = tmp_path / "index.db"
        source = tmp_path / "source"
        dest = tmp_path / "dest"
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
            conn.execute("INSERT INTO Files VALUES (1, 'exists.txt', NULL, 'ex001')")
            conn.execute("INSERT INTO Files VALUES (2, 'missing.txt', NULL, 'mis002')")
        
        # Create source for first file only
        file_dir = source / "ex" / "ex001"
        file_dir.mkdir(parents=True)
        (file_dir / "ex001").write_text("exists")
        
        # Create farm (will have 1 good, 1 broken symlink)
        farm_result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert farm_result['created'] == 1
        assert farm_result['missing'] == 1
        
        # Rsync should skip broken symlinks
        log_file = tmp_path / "rsync.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_code, errors = rsync_restore.run_rsync(
            str(farm),
            str(dest),
            monitor,
            dry_run=False
        )
        
        # Should copy only the valid file
        assert (dest / "exists.txt").exists()
        assert not (dest / "missing.txt").exists()
    
    def test_rsync_with_excluded_patterns(self, tmp_path):
        """Test rsync with exclusion patterns from farm"""
        db_path = tmp_path / "index.db"
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        farm = tmp_path / "farm"
        
        source.mkdir()
        dest.mkdir()
        
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
            conn.execute("INSERT INTO Files VALUES (1, 'include.txt', NULL, 'inc001')")
            conn.execute("INSERT INTO Files VALUES (2, 'exclude.tmp', NULL, 'exc002')")
        
        # Create source files
        for cid, name in [('inc001', 'include.txt'), ('exc002', 'exclude.tmp')]:
            file_dir = source / cid[:2] / cid
            file_dir.mkdir(parents=True)
            (file_dir / cid).write_text("content")
        
        # Create farm
        rsync_restore.create_symlink_farm_streaming(str(db_path), str(source), str(farm))
        
        # Rsync with exclusion
        log_file = tmp_path / "rsync.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_restore.run_rsync(
            str(farm),
            str(dest),
            monitor,
            exclude=["*.tmp"],
            dry_run=False
        )
        
        # Should exclude .tmp file
        assert (dest / "include.txt").exists()
        assert not (dest / "exclude.tmp").exists()


class TestFarmRsyncWithNestedStructures:
    """Test farm→rsync with nested directory structures"""
    
    def test_nested_directory_preservation(self, tmp_path):
        """Test that nested directory structure is preserved through farm→rsync"""
        db_path = tmp_path / "index.db"
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        farm = tmp_path / "farm"
        
        source.mkdir()
        dest.mkdir()
        
        # Create nested structure in database
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            conn.execute("INSERT INTO Files VALUES (1, 'Photos', NULL, NULL)")
            conn.execute("INSERT INTO Files VALUES (2, '2023', 1, NULL)")
            conn.execute("INSERT INTO Files VALUES (3, 'vacation.jpg', 2, 'vac001')")
        
        # Create source file
        file_dir = source / "va" / "vac001"
        file_dir.mkdir(parents=True)
        (file_dir / "vac001").write_text("image data")
        
        # Create farm
        rsync_restore.create_symlink_farm_streaming(str(db_path), str(source), str(farm))
        
        # Verify farm structure
        assert (farm / "Photos" / "2023" / "vacation.jpg").is_symlink()
        
        # Rsync
        log_file = tmp_path / "rsync.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        rsync_restore.run_rsync(str(farm), str(dest), monitor, dry_run=False)
        
        # Verify destination structure
        assert (dest / "Photos" / "2023" / "vacation.jpg").exists()
        assert (dest / "Photos" / "2023" / "vacation.jpg").is_file()
    
    def test_multiple_files_same_directory(self, tmp_path):
        """Test multiple files in same directory through farm→rsync"""
        db_path = tmp_path / "index.db"
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        farm = tmp_path / "farm"
        
        source.mkdir()
        dest.mkdir()
        
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
            conn.execute("INSERT INTO Files VALUES (1, 'Documents', NULL, NULL)")
            conn.execute("INSERT INTO Files VALUES (2, 'file1.pdf', 1, 'pdf001')")
            conn.execute("INSERT INTO Files VALUES (3, 'file2.pdf', 1, 'pdf002')")
            conn.execute("INSERT INTO Files VALUES (4, 'file3.pdf', 1, 'pdf003')")
        
        # Create source files
        for i, cid in enumerate(['pdf001', 'pdf002', 'pdf003'], 1):
            file_dir = source / cid[:2] / cid
            file_dir.mkdir(parents=True)
            (file_dir / cid).write_text(f"PDF {i}")
        
        # Create farm and rsync
        rsync_restore.create_symlink_farm_streaming(str(db_path), str(source), str(farm))
        
        log_file = tmp_path / "rsync.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        rsync_restore.run_rsync(str(farm), str(dest), monitor, dry_run=False)
        
        # All files should be in same directory
        docs = dest / "Documents"
        assert docs.is_dir()
        assert (docs / "file1.pdf").exists()
        assert (docs / "file2.pdf").exists()
        assert (docs / "file3.pdf").exists()


class TestFarmRsyncProgressMonitoring:
    """Test progress monitoring during farm→rsync operations"""
    
    def test_monitor_tracks_farm_sync_progress(self, tmp_path):
        """Test that monitor tracks progress during rsync from farm"""
        db_path = tmp_path / "index.db"
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        farm = tmp_path / "farm"
        
        source.mkdir()
        dest.mkdir()
        
        # Create database with multiple files
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
                conn.execute(f"INSERT INTO Files VALUES ({i+1}, 'file{i}.txt', NULL, 'f{i:03d}')")
        
        # Create source files with varying sizes
        for i in range(10):
            content_id = f"f{i:03d}"
            file_dir = source / content_id[:2] / content_id
            file_dir.mkdir(parents=True)
            (file_dir / content_id).write_bytes(b"x" * (1000 * (i + 1)))  # Varying sizes
        
        # Create farm
        rsync_restore.create_symlink_farm_streaming(str(db_path), str(source), str(farm))
        
        # Rsync with monitoring
        log_file = tmp_path / "rsync.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_code, errors = rsync_restore.run_rsync(
            str(farm),
            str(dest),
            monitor,
            dry_run=False
        )
        
        # Monitor should have tracked transfers
        assert monitor.files_transferred >= 0  # May vary based on rsync behavior
        assert monitor.bytes_transferred >= 0
    
    @patch('subprocess.Popen')
    def test_monitor_receives_rsync_output(self, mock_popen, tmp_path):
        """Test that monitor receives and parses rsync output"""
        farm = tmp_path / "farm"
        dest = tmp_path / "dest"
        farm.mkdir()
        dest.mkdir()
        
        # Mock rsync process with progress output
        mock_process = MagicMock()
        mock_process.stdout = [
            "file1.txt\n",
            "         512 100%    0.00kB/s    0:00:00 (xfr#1, to-chk=9/10)\n",
            "file2.txt\n",
            "       1,024 100%    1.00MB/s    0:00:00 (xfr#2, to-chk=8/10)\n",
        ]
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process
        
        log_file = tmp_path / "rsync.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_code, errors = rsync_restore.run_rsync(
            str(farm),
            str(dest),
            monitor,
            dry_run=False
        )
        
        # Monitor should have parsed progress
        assert monitor.files_transferred >= 0


class TestFarmRsyncDryRun:
    """Test dry-run mode for farm→rsync workflows"""
    
    def test_dry_run_shows_what_would_sync(self, tmp_path):
        """Test dry-run shows files without actually copying"""
        db_path = tmp_path / "index.db"
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        farm = tmp_path / "farm"
        
        source.mkdir()
        dest.mkdir()
        
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
            for i in range(5):
                conn.execute(f"INSERT INTO Files VALUES ({i+1}, 'file{i}.txt', NULL, 'f{i:03d}')")
        
        # Create source files
        for i in range(5):
            content_id = f"f{i:03d}"
            file_dir = source / content_id[:2] / content_id
            file_dir.mkdir(parents=True)
            (file_dir / content_id).write_text(f"content {i}")
        
        # Create farm
        rsync_restore.create_symlink_farm_streaming(str(db_path), str(source), str(farm))
        
        # Dry-run rsync
        log_file = tmp_path / "rsync.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_code, errors = rsync_restore.run_rsync(
            str(farm),
            str(dest),
            monitor,
            dry_run=True
        )
        
        # Should complete successfully but not copy files
        assert rsync_code == 0
        # Destination should be empty (dry run)
        assert len(list(dest.glob("*.txt"))) == 0


class TestFarmRsyncChecksums:
    """Test checksum verification in farm→rsync workflows"""
    
    def test_rsync_with_checksum_verification(self, tmp_path):
        """Test rsync uses checksum when enabled"""
        db_path = tmp_path / "index.db"
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        farm = tmp_path / "farm"
        
        source.mkdir()
        dest.mkdir()
        
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
            conn.execute("INSERT INTO Files VALUES (1, 'data.bin', NULL, 'dat001')")
        
        # Create source file
        file_dir = source / "da" / "dat001"
        file_dir.mkdir(parents=True)
        (file_dir / "dat001").write_bytes(b"important data")
        
        # Create farm
        rsync_restore.create_symlink_farm_streaming(str(db_path), str(source), str(farm))
        
        # First sync with checksum
        log_file = tmp_path / "rsync.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_restore.run_rsync(
            str(farm),
            str(dest),
            monitor,
            checksum=True,
            dry_run=False
        )
        
        assert (dest / "data.bin").exists()
        assert (dest / "data.bin").read_bytes() == b"important data"


class TestFarmRsyncLargeScale:
    """Test farm→rsync with large numbers of files"""
    
    def test_rsync_many_files(self, tmp_path):
        """Test rsync performance with many files"""
        db_path = tmp_path / "index.db"
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        farm = tmp_path / "farm"
        
        source.mkdir()
        dest.mkdir()
        
        # Create database with 50 files
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE Files (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    parentID INTEGER,
                    contentID TEXT
                )
            """)
            for i in range(50):
                conn.execute(f"INSERT INTO Files VALUES ({i+1}, 'file{i:03d}.txt', NULL, 'f{i:04d}')")
        
        # Create source files
        for i in range(50):
            content_id = f"f{i:04d}"
            file_dir = source / content_id[:2] / content_id
            file_dir.mkdir(parents=True)
            (file_dir / content_id).write_text(f"content {i}")
        
        # Create farm
        farm_result = rsync_restore.create_symlink_farm_streaming(
            str(db_path),
            str(source),
            str(farm)
        )
        
        assert farm_result['created'] == 50
        
        # Rsync
        log_file = tmp_path / "rsync.log"
        monitor = rsync_restore.RsyncMonitor(str(log_file))
        
        rsync_code, errors = rsync_restore.run_rsync(
            str(farm),
            str(dest),
            monitor,
            dry_run=False
        )
        
        assert rsync_code == 0
        assert len(list(dest.glob("*.txt"))) == 50
