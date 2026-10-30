"""
Production line: flash the same image onto board after board, one at a
time.

rkdeveloptool refuses every command while more than one Rockchip device is
connected ("Found too many rockusb devices") and has no way to pick one, so
boards go through one after another: plug in a board in Maskrom, the line
loads the Loader, checks the image fits, writes it, optionally reads it
back, resets the board, and asks for the next one once this one is
unplugged. Each step runs through the window's run_command, so progress,
cancelling, losing the board mid-write and the failure explanations work as
they do for a single write.
"""
import os
import shutil
import tempfile
import time

from PySide6.QtCore import QTimer

from . import loader_fetch, operations
from .utils import RKTOOL, flash_capacity_bytes, format_file_size, safe_slot
from .workers import CallWorker, FileHashWorker

IDLE = "idle"
PREPARING = "preparing"       # decompressing / hashing the image
WAITING = "waiting"           # for exactly one board
RUNNING = "running"           # flashing the board
UNPLUG = "unplug"             # board done (or failed); waiting for it to go

SECTOR = 512
# rkdeveloptool needs a moment after db before the board answers again.
AFTER_DB_MS = 1500
RFI_ATTEMPTS = 3


class ProductionLine:
    def __init__(self, gui):
        self.gui = gui
        self.state = IDLE
        self.image = None           # the plain image being written
        self.md5 = ""               # set when reading back is on
        self.verify = False
        self.ok = 0
        self.failed = 0
        self._cleanup = lambda: None
        self._board = None          # per-board details while RUNNING/UNPLUG
        self._loaders = {}          # chip -> Loader fetched from rkbin
        self._workers = []          # background workers to keep alive

    # Start / stop
    @property
    def active(self):
        return self.state != IDLE

    @property
    def busy(self):
        """While True the window leaves the device to the line."""
        return self.state == RUNNING

    def start(self, image_path, verify):
        if self.active:
            return
        self.ok = self.failed = 0
        self.verify = verify
        self._set(PREPARING, self.tr("line_preparing"))

        def ready(path, cleanup):
            if self.state != PREPARING:     # stopped meanwhile
                cleanup()
                return
            self.image, self._cleanup = path, cleanup
            if not verify:
                self._wait_for_board()
                return
            worker = FileHashWorker(path)
            self._keep(worker)
            worker.progress.connect(safe_slot(self.gui.progress_bar.setValue))

            def hashed(md5sum):
                if self.state != PREPARING:
                    return
                self.gui.progress_bar.setValue(0)
                if not md5sum:
                    self._stop(self.tr("line_hash_failed"))
                    return
                self.md5 = md5sum
                self._wait_for_board()

            worker.finished.connect(safe_slot(hashed))
            worker.start()

        operations._with_plain_image(self.gui, image_path, ready)
        # _with_plain_image explains and refuses some images without calling
        # back: right away, or after decompressing (a failure, or an
        # update.img inside). Its own handlers run first.
        decompressing = getattr(self.gui, '_decompress_worker', None)
        if decompressing is not None and decompressing.isRunning():
            def unpacked(*_):
                if self.state == PREPARING and self.image is None:
                    self._stop()
            decompressing.finished.connect(safe_slot(unpacked))
            decompressing.failed.connect(safe_slot(unpacked))
        elif self.state == PREPARING and self.image is None:
            self._stop()

    def stop(self):
        """Stop the line. A write in progress is cancelled the usual way
        (which asks first)."""
        if self.state == RUNNING and getattr(self.gui, '_command_active', False):
            self.gui.cancel_current()
            if not getattr(self.gui, '_cancel_requested', False):
                return          # the user chose to let the write finish
        self._stop()

    def _stop(self, reason=None):
        self.state = IDLE
        self._board = None
        self._cleanup()
        self._cleanup = lambda: None
        self.image = None
        self.md5 = ""
        decompressing = getattr(self.gui, '_decompress_worker', None)
        if decompressing is not None and decompressing.isRunning():
            decompressing.stop()
        self.gui._update_poll_mode()
        self.gui.on_production_changed(reason or self.tr("line_stopped"))

    # Boards coming and going
    def device_changed(self):
        """Called by the window after every device poll."""
        gui = self.gui
        devices = getattr(gui, 'connected_devices', None) or []
        if self.state == UNPLUG and not devices:
            self._wait_for_board()
        elif self.state == WAITING and devices:
            if len(devices) > 1:
                self._set(WAITING, self.tr("line_one_at_a_time").format(len(devices)))
            else:
                self._start_board()

    def _wait_for_board(self):
        self._board = None
        self._set(WAITING, self.tr("line_waiting"))
        self.device_changed()

    def _start_board(self):
        gui = self.gui
        self._board = {
            "chip": operations.loader_chip(gui) or "",
            "started": time.monotonic(),
            "device": gui.current_device,
        }
        self._set(RUNNING, self.tr("line_running").format(self._chip_text()))
        gui._update_poll_mode()
        if 'Maskrom' in (getattr(gui, 'device_mode', '') or ''):
            self._load_loader()
        else:
            self._read_capacity(RFI_ATTEMPTS)

    # The steps for one board
    def _load_loader(self):
        gui = self.gui
        path = gui.loader_path.text().strip()
        if path and os.path.isfile(path):
            self._run_db(path)
            return
        chip = self._board["chip"]
        if chip in self._loaders:
            self._run_db(self._loaders[chip])
            return
        if not chip:
            self._fail(self.tr("line_no_loader"))
            return
        self._set(RUNNING, self.tr("line_fetching_loader").format(chip))
        worker = loader_fetch.LoaderFetchWorker(chip, operations.loader_cache_dir())
        self._keep(worker)

        def fetched(path, ini_name, sha):
            if self.state != RUNNING:
                return
            self._loaders[chip] = path
            gui.log_message(f"[OK] {self.tr('fetch_loader_done').format(os.path.basename(path), ini_name)}")
            self._run_db(path)

        def failed(kind, error):
            if self.state == RUNNING:
                self._fail(self.tr("line_no_loader"), error)

        worker.finished_ok.connect(safe_slot(fetched))
        worker.failed.connect(safe_slot(failed))
        worker.start()

    def _run_db(self, loader):
        def done(success, output):
            if self.state != RUNNING:
                return
            if success:
                self.gui.loader_loaded = True
            # db also fails when a Loader is already running; rfi tells.
            QTimer.singleShot(AFTER_DB_MS, lambda: self._read_capacity(
                RFI_ATTEMPTS, db_output=None if success else output))

        self._set(RUNNING, self.tr("line_loading_loader").format(self._chip_text()))
        self._run([RKTOOL, "db", loader], "loading_loader", done)

    def _read_capacity(self, attempts, db_output=None):
        if self.state != RUNNING:
            return

        def done(success, output):
            if self.state != RUNNING:
                return
            capacity = flash_capacity_bytes(output) if success else None
            if capacity is None and attempts > 1:
                QTimer.singleShot(AFTER_DB_MS, lambda: self._read_capacity(attempts - 1, db_output))
                return
            if capacity is None:
                self._fail(self.tr("line_no_answer"), db_output or output)
                return
            self.gui.loader_loaded = True
            size = os.path.getsize(self.image)
            if size > capacity:
                self._fail(self.tr("pf_capacity_too_big").format(
                    format_file_size(size), format_file_size(capacity)))
                return
            self._write()

        self._run([RKTOOL, "rfi"], "reading_flash_info", done)

    def _write(self):
        gui = self.gui
        size = os.path.getsize(self.image)
        name = os.path.basename(self.image)
        gui.begin_job(size * 2 if self.verify else size)
        gui.job_stage(self.tr("stage_writing").format(name), 0, size)
        self._set(RUNNING, self.tr("line_writing").format(self._chip_text()))

        def done(success, output):
            if self.state != RUNNING:
                return
            if not success:
                self._fail_from(output)
            elif self.verify:
                self._read_back(size)
            else:
                self._reset()

        self._run([RKTOOL, "wl", "0x0", self.image], "burning", done)

    def _read_back(self, size):
        gui = self.gui
        name = os.path.basename(self.image)
        tmp_dir = tempfile.mkdtemp(prefix="rkdevtool_line_")
        readback = os.path.join(tmp_dir, "readback.bin")
        gui.begin_job(size * 2)
        gui.job_stage(self.tr("stage_verifying").format(name), size, size)
        self._set(RUNNING, self.tr("line_verifying").format(self._chip_text()))

        def finish(error=None, detail=None):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            if self.state != RUNNING:
                return
            if error:
                self._fail(error, detail)
            else:
                self._reset()

        def read(success, output):
            if self.state != RUNNING:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return
            if not success:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                self._fail_from(output)
                return
            worker = FileHashWorker(readback, length=size)
            self._keep(worker)

            def compared(md5sum):
                if md5sum == self.md5:
                    finish()
                    return
                from .utils import find_readback_filler
                scan = CallWorker(lambda: find_readback_filler(readback, self.image, size))
                self._keep(scan)

                def scanned(filler_at):
                    if isinstance(filler_at, int):
                        # The loader can't read this far back: unverified,
                        # not bad. Count the board and say so.
                        self._board["note"] = self.tr("line_unverified").format(
                            format_file_size(filler_at))
                        finish()
                    else:
                        finish(self.tr("verify_mismatch_title"), f"{md5sum} != {self.md5}")

                scan.finished.connect(safe_slot(scanned))
                scan.start()

            worker.finished.connect(safe_slot(compared))
            worker.start()

        sectors = -(-size // SECTOR)
        self._run([RKTOOL, "rl", "0x0", hex(sectors), readback], "verifying", read)

    def _reset(self):
        def done(success, output):
            if self.state != RUNNING:
                return
            # The image is written; a board that doesn't take the reset
            # still has it, so this only goes into the note.
            if not success:
                self._board["note"] = self.tr("line_reset_failed")
            self._succeed()

        self._run([RKTOOL, "rd"], "rebooting", done)

    # Results
    def _succeed(self):
        self.ok += 1
        board = self._board
        note = board.get("note", "")
        self._record(True, self.tr("line_board_ok").format(self._chip_text(), self._elapsed()), note)
        self._set(UNPLUG, self.tr("line_unplug_ok"))

    def _fail_from(self, output):
        gui = self.gui
        if getattr(gui, '_cancel_requested', False):
            return      # stop() winds the line down
        if getattr(gui, '_lost_during_write', False):
            self._fail(self.tr("lost_during_write_title"), output)
            return
        guidance = gui.explain_failure(output)
        self._fail(guidance[0] if guidance else self.tr("line_step_failed"), output)

    def _fail(self, reason, detail=None):
        self.failed += 1
        self.gui.end_job()
        lines = (detail or "").strip().splitlines()
        self._record(False, self.tr("line_board_failed").format(self._chip_text(), reason),
                     lines[-1] if lines else "")
        self._set(UNPLUG, self.tr("line_unplug_failed").format(reason.rstrip("。.")))

    def _record(self, success, text, note=""):
        self.gui.log_message(f"[{'OK' if success else 'ERROR'}] {text}" + (f" ({note})" if note else ""))
        self.gui.on_production_board(success, text, note)

    # Helpers
    def _run(self, cmd, key, callback):
        # The previous step's worker may still be exiting.
        operations._run_when_idle(self.gui, cmd, key, callback)

    def _set(self, state, status):
        self.state = state
        self.gui._update_poll_mode()
        self.gui.on_production_changed(status)

    def _keep(self, worker):
        self._workers = [w for w in self._workers if w.isRunning()] + [worker]

    def wait(self, ms):
        for worker in self._workers:
            if worker.isRunning():
                worker.wait(ms)

    def _chip_text(self):
        board = self._board or {}
        return board.get("chip") or self.tr("unknown_chip")

    def _elapsed(self):
        seconds = int(time.monotonic() - (self._board or {}).get("started", time.monotonic()))
        return f"{seconds // 60}:{seconds % 60:02d}"

    def tr(self, key):
        return self.gui.tr(key)
