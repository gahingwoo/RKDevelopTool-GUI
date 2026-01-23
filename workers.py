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
                result = subprocess.run([RKTOOL, "ld"], capture_output=True, text=True, timeout=3)
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
            result = subprocess.run([RKTOOL, "rci"], capture_output=True, text=True, timeout=3)
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
            result = subprocess.run([RKTOOL, "ppt"], capture_output=True, text=True, timeout=10)
            out = result.stdout or ""
            code = result.returncode
            self.finished.emit(out, code)
        except Exception as e:
            self.finished.emit(str(e), 1)


class CommandWorker(QThread):
    """Command execution worker thread"""
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

    def tr(self, key):
        return self.manager.tr(key)

    def run(self):
        try:
            description = self.tr(self.description_key)
            self.log.emit(f"🚀 {self.tr('start_executing')}{description}")
            self.log.emit(f"📝 {self.tr('command')}{' '.join(self.cmd)}")

            process = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                env={**os.environ, 'PYTHONUNBUFFERED': '1'}
            )

            self._process = process
            line_buffer = ""

            # Read output character by character for true real-time updates
            while True:
                char = process.stdout.read(1)
                if not char:
                    # Process final buffered content if any
                    if line_buffer:
                        self._process_line(line_buffer)
                    break
                
                line_buffer += char
                
                # Process when we get a complete line
                if char == '\n':
                    self._process_line(line_buffer)
                    line_buffer = ""

            returncode = process.wait()
            if returncode == 0:
                self.log.emit(f"✅ {description} {self.tr('success')}")
                # Only emit 100% if we haven't already reached it
                if self.last_logged_progress < 100:
                    self.progress.emit(100)
                self.finished_signal.emit(True, "")
            else:
                error_msg = f"{self.tr('failure')}{returncode}"
                self.log.emit(f"❌ {description} {error_msg}")
                self.progress.emit(0)
                self.finished_signal.emit(False, error_msg)
        except Exception as e:
            error_msg = str(e)
            description = self.tr(self.description_key) if 'description' in locals() else "command"
            self.log.emit(f"❌ {description} {self.tr('abnormal_execution')}{error_msg}")
            self.progress.emit(0)
            self.finished_signal.emit(False, error_msg)

    def _process_line(self, line):
        """Process a single line of output"""
        # Remove ANSI control codes comprehensively
        line_cleaned = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', line)  # Binary ANSI sequences
        line_cleaned = re.sub(r'\[1A\[2K|\[2K|\[1A', '', line_cleaned)  # Text-form control codes
        line_cleaned = line_cleaned.strip()
        
        if not line_cleaned:
            return
        
        # Only log lines that are not just progress updates
        if "%" in line_cleaned:
            match = re.search(r'(\d+)%', line_cleaned)
            if match:
                progress = min(int(match.group(1)), 99)
                # Only emit progress and log if it's different from last
                if progress != self.last_logged_progress:
                    self.log.emit(line_cleaned)
                    self.progress.emit(progress)
                    self.last_logged_progress = progress
                    self.last_logged_line = line_cleaned
        else:
            # Log non-progress lines normally, but skip duplicates
            if line_cleaned != self.last_logged_line:
                self.log.emit(line_cleaned)
                self.last_logged_line = line_cleaned

    def terminate_process(self):
        """Attempt to terminate the running subprocess if any."""
        try:
            if self._process and self._process.poll() is None:
                self._process.kill()
        except Exception:
            pass