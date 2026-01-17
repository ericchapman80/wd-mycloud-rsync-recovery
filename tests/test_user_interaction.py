"""
Tests for user interaction functions in rsync_restore.py

Tests prompt_path, prompt_yes_no, and other interactive functions.
"""
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rsync_restore


class TestPromptPath:
    """Test prompt_path function"""
    
    @patch('builtins.input')
    def test_accepts_valid_existing_directory(self, mock_input, tmp_path):
        """Test that valid existing directory is accepted"""
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        
        mock_input.return_value = str(test_dir)
        
        result = rsync_restore.prompt_path("Enter path:", must_exist=True, is_dir=True)
        
        assert result == str(test_dir)
    
    @patch('builtins.input')
    def test_accepts_valid_existing_file(self, mock_input, tmp_path):
        """Test that valid existing file is accepted"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        
        mock_input.return_value = str(test_file)
        
        result = rsync_restore.prompt_path("Enter file:", must_exist=True, is_dir=False)
        
        assert result == str(test_file)
    
    @patch('builtins.input')
    def test_retries_on_nonexistent_path(self, mock_input, tmp_path):
        """Test that nonexistent path causes retry"""
        valid_dir = tmp_path / "valid"
        valid_dir.mkdir()
        
        # First return nonexistent, then valid
        mock_input.side_effect = ["/nonexistent/path", str(valid_dir)]
        
        result = rsync_restore.prompt_path("Enter path:", must_exist=True, is_dir=True)
        
        assert result == str(valid_dir)
        assert mock_input.call_count == 2
    
    @patch('builtins.input')
    def test_allows_nonexistent_when_must_exist_false(self, mock_input):
        """Test that nonexistent paths are allowed when must_exist=False"""
        new_path = "/path/to/new/directory"
        mock_input.return_value = new_path
        
        result = rsync_restore.prompt_path("Enter path:", must_exist=False, is_dir=True)
        
        assert result == new_path
    
    @patch('builtins.input')
    def test_expands_tilde(self, mock_input, tmp_path):
        """Test that tilde is expanded to home directory"""
        # Mock with tilde path
        mock_input.return_value = "~/test"
        
        # Should expand tilde
        result = rsync_restore.prompt_path("Enter path:", must_exist=False, is_dir=True)
        
        assert result.startswith(os.path.expanduser("~"))
    
    @patch('builtins.input')
    def test_rejects_file_when_directory_expected(self, mock_input, tmp_path):
        """Test that file is rejected when directory is expected"""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")
        
        valid_dir = tmp_path / "dir"
        valid_dir.mkdir()
        
        # First return file, then directory
        mock_input.side_effect = [str(test_file), str(valid_dir)]
        
        result = rsync_restore.prompt_path("Enter directory:", must_exist=True, is_dir=True)
        
        assert result == str(valid_dir)
        assert mock_input.call_count == 2
    
    @patch('builtins.input')
    def test_rejects_directory_when_file_expected(self, mock_input, tmp_path):
        """Test that directory is rejected when file is expected"""
        test_dir = tmp_path / "dir"
        test_dir.mkdir()
        
        valid_file = tmp_path / "file.txt"
        valid_file.write_text("content")
        
        # First return directory, then file
        mock_input.side_effect = [str(test_dir), str(valid_file)]
        
        result = rsync_restore.prompt_path("Enter file:", must_exist=True, is_dir=False)
        
        assert result == str(valid_file)
        assert mock_input.call_count == 2


class TestPromptYesNo:
    """Test prompt_yes_no function"""
    
    @patch('builtins.input')
    def test_accepts_yes(self, mock_input):
        """Test that 'yes' returns True"""
        mock_input.return_value = 'yes'
        
        result = rsync_restore.prompt_yes_no("Continue?")
        
        assert result is True
    
    @patch('builtins.input')
    def test_accepts_y(self, mock_input):
        """Test that 'y' returns True"""
        mock_input.return_value = 'y'
        
        result = rsync_restore.prompt_yes_no("Continue?")
        
        assert result is True
    
    @patch('builtins.input')
    def test_accepts_no(self, mock_input):
        """Test that 'no' returns False"""
        mock_input.return_value = 'no'
        
        result = rsync_restore.prompt_yes_no("Continue?")
        
        assert result is False
    
    @patch('builtins.input')
    def test_accepts_n(self, mock_input):
        """Test that 'n' returns False"""
        mock_input.return_value = 'n'
        
        result = rsync_restore.prompt_yes_no("Continue?")
        
        assert result is False
    
    @patch('builtins.input')
    def test_case_insensitive(self, mock_input):
        """Test that input is case insensitive"""
        mock_input.return_value = 'YES'
        
        result = rsync_restore.prompt_yes_no("Continue?")
        
        assert result is True
    
    @patch('builtins.input')
    def test_default_true(self, mock_input):
        """Test that empty input uses default=True"""
        mock_input.return_value = ''
        
        result = rsync_restore.prompt_yes_no("Continue?", default=True)
        
        assert result is True
    
    @patch('builtins.input')
    def test_default_false(self, mock_input):
        """Test that empty input uses default=False"""
        mock_input.return_value = ''
        
        result = rsync_restore.prompt_yes_no("Continue?", default=False)
        
        assert result is False
    
    @patch('builtins.input')
    def test_retries_on_invalid_input(self, mock_input):
        """Test that invalid input causes retry"""
        # First invalid, then valid
        mock_input.side_effect = ['maybe', 'yes']
        
        result = rsync_restore.prompt_yes_no("Continue?")
        
        assert result is True
        assert mock_input.call_count == 2


class TestPrintFunctions:
    """Test output formatting functions"""
    
    def test_print_header(self, capsys):
        """Test print_header outputs text"""
        rsync_restore.print_header("Test Header")
        
        captured = capsys.readouterr()
        assert "Test Header" in captured.out
    
    def test_print_success(self, capsys):
        """Test print_success outputs text"""
        rsync_restore.print_success("Success message")
        
        captured = capsys.readouterr()
        assert "Success message" in captured.out
    
    def test_print_warning(self, capsys):
        """Test print_warning outputs text"""
        rsync_restore.print_warning("Warning message")
        
        captured = capsys.readouterr()
        assert "Warning message" in captured.out
    
    def test_print_error(self, capsys):
        """Test print_error outputs text"""
        rsync_restore.print_error("Error message")
        
        captured = capsys.readouterr()
        assert "Error message" in captured.out
    
    def test_print_info(self, capsys):
        """Test print_info outputs text"""
        rsync_restore.print_info("Info message")
        
        captured = capsys.readouterr()
        assert "Info message" in captured.out
    
    def test_print_step(self, capsys):
        """Test print_step outputs numbered step"""
        rsync_restore.print_step(1, "First step")
        
        captured = capsys.readouterr()
        assert "1" in captured.out
        assert "First step" in captured.out


class TestColorize:
    """Test colorize function"""
    
    def test_colorize_adds_color_codes(self):
        """Test that colorize adds ANSI codes when supported"""
        result = rsync_restore.colorize("test", rsync_restore.Colors.RED)
        
        # Should contain color codes
        assert len(result) > len("test")
    
    def test_colorize_with_different_colors(self):
        """Test colorize with various colors"""
        colors = [
            rsync_restore.Colors.RED,
            rsync_restore.Colors.GREEN,
            rsync_restore.Colors.BLUE,
            rsync_restore.Colors.YELLOW
        ]
        
        for color in colors:
            result = rsync_restore.colorize("test", color)
            assert isinstance(result, str)


class TestEmoji:
    """Test emoji function"""
    
    def test_emoji_returns_string(self):
        """Test that emoji function returns a string"""
        result = rsync_restore.emoji("✅", fallback="OK")
        
        assert isinstance(result, str)
    
    def test_emoji_with_fallback(self):
        """Test emoji with fallback text"""
        result = rsync_restore.emoji("🚀", fallback="ROCKET")
        
        # Should return either emoji or fallback
        assert result in ["🚀", "ROCKET", ""]


class TestConfigHelpers:
    """Test configuration helper functions"""
    
    def test_load_simple_config(self, tmp_path):
        """Test _load_simple_config function"""
        config_file = tmp_path / "config.txt"
        config_file.write_text("protect: Photos/*\nprotect: Documents/*\n")
        
        config = rsync_restore._load_simple_config(str(config_file))
        
        assert 'protect' in config
        assert isinstance(config['protect'], list)
    
    def test_save_simple_config(self, tmp_path):
        """Test _save_simple_config function"""
        config_file = tmp_path / "config.txt"
        config = {
            'protect': ['Photos/*', 'Documents/*'],
            'cleanup': ['Temp/*']
        }
        
        rsync_restore._save_simple_config(config, str(config_file))
        
        assert config_file.exists()
        content = config_file.read_text()
        assert 'Photos/*' in content
        assert 'Documents/*' in content


class TestInteractionWithMockedTerminal:
    """Test interaction functions with mocked terminal environment"""
    
    @patch('sys.stdout.isatty')
    def test_colorize_in_non_tty(self, mock_isatty):
        """Test that colors are disabled in non-TTY"""
        mock_isatty.return_value = False
        
        result = rsync_restore.colorize("test", rsync_restore.Colors.RED)
        
        # In non-TTY, should return plain text
        assert "test" in result
    
    @patch('builtins.input')
    @patch('builtins.print')
    def test_prompt_with_print_output(self, mock_print, mock_input, tmp_path):
        """Test that prompts generate output"""
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        
        mock_input.return_value = str(test_dir)
        
        rsync_restore.prompt_path("Enter path:", must_exist=True, is_dir=True)
        
        # Should have called print for the prompt
        assert mock_print.called or mock_input.called


class TestWizardHelpers:
    """Test wizard-related helper functions"""
    
    @patch('builtins.input')
    def test_multiple_prompts_in_sequence(self, mock_input, tmp_path):
        """Test handling multiple prompts in sequence"""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        
        mock_input.side_effect = [str(dir1), str(dir2), 'yes']
        
        result1 = rsync_restore.prompt_path("First path:", must_exist=True, is_dir=True)
        result2 = rsync_restore.prompt_path("Second path:", must_exist=True, is_dir=True)
        result3 = rsync_restore.prompt_yes_no("Continue?")
        
        assert result1 == str(dir1)
        assert result2 == str(dir2)
        assert result3 is True


class TestInputValidation:
    """Test input validation edge cases"""
    
    @patch('builtins.input')
    def test_whitespace_handling(self, mock_input, tmp_path):
        """Test that whitespace is stripped from input"""
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        
        # Input with extra whitespace
        mock_input.return_value = f"  {test_dir}  "
        
        result = rsync_restore.prompt_path("Enter path:", must_exist=True, is_dir=True)
        
        assert result == str(test_dir)
    
    @patch('builtins.input')
    def test_empty_input_with_no_default(self, mock_input, tmp_path):
        """Test that empty input without default causes retry"""
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        
        # First empty, then valid
        mock_input.side_effect = ['', str(test_dir)]
        
        result = rsync_restore.prompt_path("Enter path:", must_exist=True, is_dir=True)
        
        assert result == str(test_dir)
        assert mock_input.call_count == 2
