"""
Background worker threads for RKDevelopTool GUI
"""
import subprocess
import re
import os
import time
import select
import errno
import hashlib
import lzma
import gzip
import bz2
from PySide6.QtCore import QThread, Signal

from . import rkfw
from . import utils
from .utils import RKTOOL, parse_chip_info


class DeviceWorker(QThread):
    """Device detection worker thread"""
    device_found = Signal(list, str, str)  # devices, mode, chip_info
    device_lost = Signal()
    # Light mode only: whether any Rockchip device is still listed.
    presence = Signal(bool)

    def __init__(self, manager):
        super().__init__()
        # Set here, not in run(): a stop() that lands before the thread has
        # actually started would otherwise be overwritten and the loop would
        # never end (closing the window right after it opened left a running
        # QThread behind, which aborts the process on exit).
        self.running = True
        self.manager = manager
        # Set while a command or a full flash is using the device: then only
        # `ld` runs (it just enumerates), never `rci`, which opens the device
        # and would talk to it alongside the running rkdeveloptool.
        self.light = False

    def tr(self, key):
        return self.manager.tr(key)

    def run(self):
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

                if self.light:
                    self.presence.emit(bool(devices))
                elif devices and not utils.DEVICE_LOCK.acquire(blocking=False):
                    # Something else is reading the device right now (e.g.
                    # the partition table); don't open it alongside, and
                    # don't touch the device state this round.
                    self.presence.emit(True)
                elif devices:
                    utils.DEVICE_LOCK.release()
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
                if self.light:
                    self.presence.emit(False)
                else:
                    self.device_lost.emit()

            # Poll every 2 s, but notice stop() within 0.1 s.
            for _ in range(20):
                if not self.running:
                    break
                QThread.msleep(100)

    def get_chip_info(self):
        try:
            env = os.environ.copy()
            env['NO_COLOR'] = '1'
            env['CLICOLOR'] = '0'
            env['CLICOLOR_FORCE'] = '0'
            
            with utils.DEVICE_LOCK:
                result = subprocess.run([RKTOOL, "rci"], capture_output=True, text=True,
                                        timeout=3, env=env)
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
            
            # Waits for a poll's rci to finish (at most ~3 s) rather than
            # opening the device alongside it.
            with utils.DEVICE_LOCK:
                result = subprocess.run([RKTOOL, "ppt"], capture_output=True, text=True,
                                        timeout=10, env=env)
            out = (result.stdout or "") + (result.stderr or "")
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
        # Stop rkdeveloptool when it prints nothing for this many seconds
        # (a board that stopped answering); None waits forever.
        self.idle_timeout = None
        self.timed_out = False

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
        last_output = time.monotonic()
        try:
            while True:
                ready, _, _ = select.select([master_fd], [], [], 1.0)
                if not ready:
                    if (self.idle_timeout and process.poll() is None
                            and time.monotonic() - last_output > self.idle_timeout):
                        self.timed_out = True
                        self.log.emit(f"[ERROR] {self.tr('command_timed_out').format(self.idle_timeout)}")
                        process.terminate()
                    elif process.poll() is not None and not self._drain_ready(master_fd):
                        break
                    continue
                last_output = time.monotonic()
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

    @staticmethod
    def _drain_ready(fd):
        """Whether fd still has output waiting (after the process exited)."""
        ready, _, _ = select.select([fd], [], [], 0)
        return bool(ready)

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
        # ef: "Erase Flash total 61079552, current 262144" (sectors).
        match = re.search(r'total (\d+), current (\d+)', text)
        if match and int(match.group(1)):
            return min(int(match.group(2)) * 100 // int(match.group(1)), 99)
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


class RKFWPrepWorker(QThread):
    """Unpack an RKFW update.img in the background before flashing.

    CRC-verifies the embedded RKAF archive and extracts the Loader,
    parameter table and every partition image to ``tmp_dir``, all off the
    GUI thread. Progress (0-99 while working, 100 right before completion)
    is reported as a byte-weighted percentage across both passes, and every
    message is forwarded to the log so the UI stays responsive during the
    slow part of a one-click full flash.

    Emits:
        progress(int)            overall percent (byte-weighted)
        log(str)                 human-readable progress lines
        finished(dict)           extracted paths:
                                 {'loader': path, 'parameter': path|None,
                                  'parts': [(partition_name, path), ...]}
        failed(kind, message)    kind == 'crc'  -> archive CRC mismatch
                                 kind == 'error'-> message holds the reason
    """

    progress = Signal(int)
    log = Signal(str)
    finished = Signal(object)
    failed = Signal(str, str)

    def __init__(self, firmware_path, rkfw_info, rkaf_info, tmp_dir, manager,
                 verify_crc=True):
        super().__init__()
        self.firmware_path = firmware_path
        self.rkfw_info = rkfw_info
        self.rkaf_info = rkaf_info
        self.tmp_dir = tmp_dir
        self.manager = manager
        self.verify_crc = verify_crc
        self._stop = False

    def stop(self):
        """Ask the verify/unpack pass to stop at its next chunk."""
        self._stop = True

    def tr(self, key):
        return self.manager.tr(key)

    def run(self):
        try:
            self._run_inner()
        except Exception as e:
            # Never die silently in the worker thread: surface every failure
            # (including programming errors) through the failed signal so the
            # GUI can clean up the temp dir and report it.
            try:
                self.failed.emit('error', str(e))
            except Exception:
                pass

    def _run_inner(self):
        info = self.rkfw_info
        rkaf = self.rkaf_info

        param = next((p for p in rkaf.parts if p.is_parameter), None)
        parts = [(p.name, p) for p in rkaf.parts if not p.is_parameter and not p.is_self]

        # Build the extraction plan first so we know the total byte count and
        # can report a single smooth percentage across verify + unpack.
        specs = []
        total = rkaf.length if self.verify_crc else 0

        loader_path = os.path.join(self.tmp_dir, "loader.bin")
        specs.append((self.tr("rkfw_extracting_loader"), info.boot_size,
                      lambda cb: rkfw.extract_loader(
                          self.firmware_path, info, loader_path, progress_cb=cb)))
        total += info.boot_size

        param_path = None
        if param is not None:
            param_path = os.path.join(self.tmp_dir, "parameter.txt")
            param_size = max(param.size - 12, 0)
            specs.append((self.tr("rkfw_extracting_parameter"), param_size,
                          lambda cb: rkfw.extract_part(
                              self.firmware_path, info.fw_offset, param,
                              param_path, progress_cb=cb)))
            total += param_size

        part_items = []
        for i, (name, part) in enumerate(parts):
            part_path = os.path.join(self.tmp_dir, f"part_{i}.img")
            part_items.append((name, part_path))
            specs.append((name, part.size,
                          lambda cb, part=part, part_path=part_path: rkfw.extract_part(
                              self.firmware_path, info.fw_offset, part,
                              part_path, progress_cb=cb)))
            total += part.size

        done = [0]
        last_pct = [-1]

        def progress_cb(delta):
            if self._stop:
                raise rkfw.RKFWError("cancelled")
            done[0] += delta
            pct = int(done[0] * 100 // total) if total > 0 else 0
            pct = min(pct, 99)
            if pct != last_pct[0]:
                last_pct[0] = pct
                self.progress.emit(pct)

        try:
            if self.verify_crc:
                self.log.emit(f"[INFO] {self.tr('rkfw_verifying_crc')}")
                if not rkfw.verify_rkaf_crc(self.firmware_path, info.fw_offset,
                                            rkaf.length, progress_cb=progress_cb):
                    self.failed.emit('crc', '')
                    return
                self.log.emit(f"[OK] {self.tr('rkfw_crc_ok')}")
            else:
                self.log.emit(f"[INFO] {self.tr('rkfw_crc_skipped')}")

            self.log.emit(f"[INFO] {self.tr('rkfw_unpacking')}")
            for label, size, extract in specs:
                self.log.emit(f"[INFO] {label} ...")
                extract(progress_cb)
        except (rkfw.RKFWError, OSError) as e:
            self.failed.emit('cancelled' if self._stop else 'error', str(e))
            return

        self.progress.emit(100)
        self.log.emit(f"[OK] {self.tr('rkfw_unpack_done')}")
        self.finished.emit({
            'loader': loader_path,
            'parameter': param_path,
            'parts': part_items,
        })


class DecompressWorker(QThread):
    """Decompress an .img.xz / .img.gz / .img.bz2 to a plain image file.

    rkdeveloptool can only write a file as-is, so a compressed distro image
    has to be unpacked to disk first. Progress is measured on the compressed
    input, since the decompressed size isn't known up front.

    Emits:
        progress(int)            percent of the compressed input consumed
        finished(str)            path of the decompressed image
        failed(kind, message)    kind is 'nospace', 'corrupt', 'cancelled'
                                 or 'error'; the partial output is removed
    """

    progress = Signal(int)
    finished = Signal(str)
    failed = Signal(str, str)

    _OPENERS = {"xz": lzma.open, "gzip": gzip.open, "bzip2": bz2.open}

    def __init__(self, src_path, kind, dest_path):
        super().__init__()
        self.src_path = src_path
        self.kind = kind
        self.dest_path = dest_path
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            kind, message = self._run_inner()
        except Exception as e:
            kind, message = 'error', str(e)
        if kind is None:
            self.progress.emit(100)
            self.finished.emit(self.dest_path)
            return
        try:
            os.remove(self.dest_path)
        except OSError:
            pass
        self.failed.emit(kind, message)

    def _run_inner(self):
        opener = self._OPENERS[self.kind]
        total = os.path.getsize(self.src_path)
        last_pct = -1
        try:
            with open(self.src_path, "rb") as raw, \
                    opener(raw, "rb") as src, \
                    open(self.dest_path, "wb") as out:
                while True:
                    if self._stop:
                        return 'cancelled', ''
                    chunk = src.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    pct = min(int(raw.tell() * 100 // total), 99) if total else 0
                    if pct != last_pct:
                        last_pct = pct
                        self.progress.emit(pct)
        except (lzma.LZMAError, EOFError) as e:
            return 'corrupt', str(e)
        except OSError as e:
            if e.errno == errno.ENOSPC:
                return 'nospace', str(e)
            # gzip.BadGzipFile and bz2's "Invalid data stream" are OSErrors
            # without an errno: the input, not the disk, is at fault.
            if e.errno is None:
                return 'corrupt', str(e)
            return 'error', str(e)
        return None, ''


class CallWorker(QThread):
    """Run one blocking call (a device query) off the GUI thread.

    Emits finished(result), where result is the call's return value or the
    exception it raised.
    """

    finished = Signal(object)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception as e:
            result = e
        self.finished.emit(result)


class FileHashWorker(QThread):
    """Compute a file's MD5 hash in the background (big images would
    otherwise freeze the GUI for the whole read)."""

    progress = Signal(int)
    finished = Signal(str)  # hex digest, or '' on error

    def __init__(self, file_path, length=None):
        super().__init__()
        self.file_path = file_path
        # Hash only the first `length` bytes (a sector-rounded readback
        # holds more than the image it's compared with).
        self.length = length

    def run(self):
        h = hashlib.md5()
        last_pct = [-1]
        try:
            size = os.path.getsize(self.file_path)
            if self.length is not None:
                size = min(size, self.length)
            with open(self.file_path, "rb") as f:
                done = 0
                while done < size:
                    chunk = f.read(min(1024 * 1024, size - done))
                    if not chunk:
                        break
                    h.update(chunk)
                    done += len(chunk)
                    pct = int(done * 100 // size) if size > 0 else 100
                    pct = min(pct, 99)
                    if pct != last_pct[0]:
                        last_pct[0] = pct
                        self.progress.emit(pct)
        except OSError:
            self.finished.emit('')
            return
        self.progress.emit(100)
        self.finished.emit(h.hexdigest())