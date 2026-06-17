"""
Background worker threads for RKDevelopTool GUI
"""
import subprocess
import re
import os
from PySide6.QtCore import QThread, Signal

from utils import RKTOOL, parse_chip_info


class DeviceWorker(QThread):
    """Device detection worker thread"""
    device_found = Signal(list, str, str)  # devices, mode, chip_info
    device_lost = Signal()

    def __init__(self, manager):
        super().__init__()
        self.running = False
        self.manager = manager

    def tr(self, key):
        return self.manager.tr(key)

    def run(self):
        self.running = True
        while self.running:
            try:
                # Disable color output
                env = os.environ.copy()
                env['NO_COLOR'] = '1'
                env['CLICOLOR'] = '0'
                env['CLICOLOR_FORCE'] = '0'
                
                result = subprocess.run([RKTOOL, "ld"], capture_output=True, text=True, timeout=3, env=env)
                lines = result.stdout.strip().splitlines()
                devices = [l for l in lines if "Did not find any rockusb device" not in l
                           and "not found" not in l and l.strip()]

                if devices:
                    mode = "unknown_mode"
                    if "MASKROM" in result.stdout.upper():
                        mode = "Maskrom"
                    elif "LOADER" in result.stdout.upper():
                        mode = "Loader"

                    chip_info = self.get_chip_info()
                    self.device_found.emit(devices, mode, chip_info)
                else:
                    self.device_lost.emit()

            except Exception:
                self.device_lost.emit()

            QThread.msleep(2000)

    def get_chip_info(self):
        try:
            env = os.environ.copy()
            env['NO_COLOR'] = '1'
            env['CLICOLOR'] = '0'
            env['CLICOLOR_FORCE'] = '0'
            
            result = subprocess.run([RKTOOL, "rci"], capture_output=True, text=True, timeout=3, env=env)
            if result.returncode == 0:
                raw_info = result.stdout.strip()
                return parse_chip_info(raw_info)
        except Exception:
            pass
        return "unknown_chip"

    def stop(self):
        self.running = False


class PartitionPPTWorker(QThread):
    """Background worker to run `rkdeveloptool ppt` and emit output."""
    finished = Signal(str, int)

    def __init__(self):
        super().__init__()

    def run(self):
        try:
            # Disable color output
            env = os.environ.copy()
            env['NO_COLOR'] = '1'
            env['CLICOLOR'] = '0'
            env['CLICOLOR_FORCE'] = '0'
            
            result = subprocess.run([RKTOOL, "ppt"], capture_output=True, text=True, timeout=10, env=env)
            out = result.stdout or ""
            # Clean ANSI codes from output
            out = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', out)  # Binary ESC sequences
            out = re.sub(r'\[[0-9;]*m', '', out)  # Text-form color codes
            out = re.sub(r'\[[0-9]+[A-K]', '', out)  # Text-form cursor/clear codes
            code = result.returncode
            self.finished.emit(out, code)
        except Exception as e:
            self.finished.emit(str(e), 1)


class CommandWorker(QThread):
    """Command execution worker thread with real-time stdout streaming"""
    progress = Signal(int)
    log = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, cmd, description_key, manager):
        super().__init__()
        self.cmd = cmd
        self.description_key = description_key
        self.manager = manager
        self._process = None
        self.last_logged_progress = -1
        self.last_logged_line = ""
        self.output = ""  # Store command output for callbacks
        self.chunk_buffer = ""  # Buffer for small chunks to reduce signal overhead

    def tr(self, key):
        return self.manager.tr(key)

    def run(self):
        """Run command with real-time stdout streaming"""
        try:
            description = self.tr(self.description_key)
            self.log.emit(f"[START] {self.tr('start_executing')}{description}")
            self.log.emit(f"[COMMAND] {self.tr('command')}{' '.join(self.cmd)}")

            # Disable color output from rkdeveloptool and set unbuffered mode
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            env['NO_COLOR'] = '1'  # Disable color output (standard convention)
            env['CLICOLOR'] = '0'  # Disable color for BSD tools
            env['CLICOLOR_FORCE'] = '0'  # Disable forced color

            self.output = ""  # Reset output buffer
            self.chunk_buffer = ""
            self.last_logged_progress = -1
            self.last_logged_line = ""

            # rkdeveloptool fully buffers its stdout when it isn't attached to a
            # terminal, so progress (e.g. "Write LBA from file (NN%)") only
            # arrives in one burst at the end -> the bar jumps 0 -> 100. Run it
            # under a pseudo-terminal on POSIX so it streams progress live.
            if os.name == 'posix':
                returncode = self._run_with_pty(env)
            else:
                returncode = self._run_with_pipe(env)

            if returncode == 0:
                self.log.emit(f"[OK] {description} {self.tr('success')}")
                # Only emit 100% if we haven't already reached it
                if self.last_logged_progress < 100:
                    self.progress.emit(100)
                self.finished_signal.emit(True, "")
            else:
                error_msg = f"{self.tr('failure')}{returncode}"
                self.log.emit(f"[ERROR] {description} {error_msg}")
                self.progress.emit(0)
                self.finished_signal.emit(False, error_msg)
        except Exception as e:
            error_msg = str(e)
            description = self.tr(self.description_key) if 'description' in locals() else "command"
            self.log.emit(f"[ERROR] {description} {self.tr('abnormal_execution')}{error_msg}")
            self.progress.emit(0)
            self.finished_signal.emit(False, error_msg)

    def _consume(self, text, line_buffer):
        """Feed raw output text, flushing a line on each newline/carriage return."""
        for ch in text:
            self.output += ch
            if ch == '\n' or ch == '\r':
                self._process_line(line_buffer)
                line_buffer = ""
            else:
                line_buffer += ch
        return line_buffer

    def _run_with_pty(self, env):
        """Run the command attached to a pseudo-terminal for live output."""
        import pty
        master_fd, slave_fd = pty.openpty()
        process = subprocess.Popen(
            self.cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
        )
        self._process = process
        os.close(slave_fd)  # parent only reads from the master end

        line_buffer = ""
        try:
            while True:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    # Linux raises EIO on the master once the child exits.
                    break
                if not data:
                    # macOS signals EOF with an empty read.
                    break
                line_buffer = self._consume(data.decode('utf-8', errors='replace'), line_buffer)
        finally:
            if line_buffer:
                self._process_line(line_buffer)
            try:
                os.close(master_fd)
            except OSError:
                pass

        return process.wait()

    def _run_with_pipe(self, env):
        """Fallback streaming via a regular pipe (e.g. on Windows)."""
        process = subprocess.Popen(
            self.cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
            env=env,
        )
        self._process = process

        line_buffer = ""
        while True:
            char = process.stdout.read(1)
            if not char:
                if line_buffer:
                    self._process_line(line_buffer)
                if self.chunk_buffer:
                    self._flush_chunk_buffer()
                break
            line_buffer = self._consume(char, line_buffer)

        return process.wait()

    def _process_line(self, line):
        """Process a single line of output - remove ANSI codes and parse progress"""
        # Clean ANSI control codes comprehensively
        line_cleaned = self._clean_ansi_codes(line)
        line_cleaned = line_cleaned.strip()
        
        if not line_cleaned:
            return
        
        # Parse progress percentage
        progress = self._extract_progress(line_cleaned)
        
        # Log and update progress
        if progress is not None:
            # Progress line - emit with deduplication
            if progress != self.last_logged_progress:
                self.log.emit(line_cleaned)
                self.progress.emit(progress)
                self.last_logged_progress = progress
                self.last_logged_line = line_cleaned
        else:
            # Regular log line - skip duplicates
            if line_cleaned != self.last_logged_line:
                self.log.emit(line_cleaned)
                self.last_logged_line = line_cleaned

    def _clean_ansi_codes(self, text):
        """Remove all ANSI control codes from text"""
        # Remove various ANSI escape sequences
        text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text)  # Binary ESC sequences
        text = re.sub(r'\[[0-9;]*m', '', text)  # Text-form color codes [30;41m, [0m, etc.
        text = re.sub(r'\[[0-9]+[A-K]', '', text)  # Text-form cursor/clear codes
        text = re.sub(r'\[1A\[2K|\[2K|\[1A', '', text)  # Additional control codes
        text = re.sub(r'\x1b\(.*?\x1b\)', '', text)  # Character set selection
        text = re.sub(r'\x0f|\x0e', '', text)  # Shift out/in
        return text
    
    def _extract_progress(self, text):
        """Extract progress percentage from text"""
        match = re.search(r'(\d+)%', text)
        if match:
            try:
                progress = int(match.group(1))
                return min(progress, 99)  # Cap at 99 to leave room for completion
            except (ValueError, AttributeError):
                pass
        return None
    
    def _flush_chunk_buffer(self):
        """Flush buffered chunks"""
        if self.chunk_buffer.strip():
            self._process_line(self.chunk_buffer)
        self.chunk_buffer = ""

    def terminate_process(self):
        """Attempt to terminate the running subprocess if any."""
        try:
            if self._process and self._process.poll() is None:
                self._process.kill()
        except Exception:
            pass