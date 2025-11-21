"""
Background worker threads for RKDevelopTool GUI
"""
import subprocess
import re
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

    def tr(self, key):
        return self.manager.tr(key)

    def run(self):
        success = False
        error_msg = ""

        try:
            description = self.tr(self.description_key)
            self.log.emit(f"🚀 {self.tr('start_executing')}{description}")
            self.log.emit(f"📝 {self.tr('command')}{' '.join(self.cmd)}")

            process = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            self._process = process

            for line in iter(process.stdout.readline, ''):
                if not line:
                    break
                line = line.strip()
                if line:
                    self.log.emit(line)
                    if "%" in line:
                        match = re.search(r'(\d+)%', line)
                        if match:
                            progress = min(int(match.group(1)), 99)
                            self.progress.emit(progress)

            process.wait()
            if process.returncode == 0:
                success = True
                self.log.emit(f"✅ {description} {self.tr('success')}")
            else:
                error_msg = f"{self.tr('failure')}{process.returncode}"
                self.log.emit(f"❌ {description} {self.tr('failure')}{process.returncode}")

        except Exception as e:
            error_msg = str(e)
            self.log.emit(f"❌ {description} {self.tr('abnormal_execution')}{error_msg}")

        self.progress.emit(100 if success else 0)
        self.finished_signal.emit(success, error_msg)

    def terminate_process(self):
        """Attempt to terminate the running subprocess if any."""
        try:
            if self._process and self._process.poll() is None:
                self._process.kill()
        except Exception:
            pass