"""Tray app: polls the dongle, feeds the tracker, draws the icon and card."""
import ctypes
import json
from logging.handlers import RotatingFileHandler
import logging
import os
from pathlib import Path
import sys
import threading
import time
import winreg

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import device, startup, text
from .card import Card
from .icons import DEFAULT_STYLE, STYLES, IconState, make_icon
from .tracker import LearnedRates, Tracker

POLL_S = 2
CONFIRM_S = 1        # a changed level is re-read quickly so plug/unplug shows fast
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ArctisBatteryTray"
MUTEX_NAME = "Local\\ArctisBatteryTray"
ERROR_ALREADY_EXISTS = 183

log = logging.getLogger("arctis_tray")


def taskbar_theme() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            light, _ = winreg.QueryValueEx(k, "SystemUsesLightTheme")
            return "light" if light else "dark"
    except OSError:
        return "dark"


class Poller(QObject):
    """Reads the dongle on a worker thread so a slow HID read never freezes
    the tray menu or card."""
    reading = Signal(object)

    def __init__(self):
        super().__init__()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._confirm = False

    def start(self):
        threading.Thread(target=self._run, name="poller", daemon=True).start()

    def refresh(self):
        self._wake.set()

    def expedite(self):
        """Take the next reading after CONFIRM_S instead of POLL_S. Called
        after the thread is already waiting, so it has to wake it."""
        self._confirm = True
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                r = device.read_battery()
            except Exception:
                log.exception("Unexpected error reading the dongle")
                r = device.Reading(device.ERROR)
            self.reading.emit(r)
            self._wake.wait(POLL_S)
            self._wake.clear()
            if self._confirm:
                self._confirm = False
                self._stop.wait(CONFIRM_S)


class Settings:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        try:
            self.path.write_text(json.dumps(self.data))
        except OSError as e:
            log.warning("Couldn't save settings: %s", e)


class App(QObject):
    def __init__(self):
        super().__init__()
        self.settings = Settings(DATA_DIR / "settings.json")
        self.tracker = Tracker(LearnedRates(DATA_DIR / "learned.json"))
        self.tracker.resume_from(self.settings.get("last_state"), time.time())
        self.saved_key, self.saved_at = None, 0.0
        self.theme = taskbar_theme()
        self.style = self.settings.get("icon_style", DEFAULT_STYLE)
        if self.style not in STYLES:
            self.style = DEFAULT_STYLE
        self.snap = None
        self.icon_key = None
        self.log_key = None

        self.card = Card()
        self.tray = QSystemTrayIcon()
        self.tray.activated.connect(self._on_activated)
        self._build_menu()
        self._set_icon(IconState("off"))
        self.tray.setToolTip(f"{text.NAME} · checking…")
        self.tray.show()

        self._first_run_autostart()

        self.poller = Poller()
        self.poller.reading.connect(self._on_reading, Qt.ConnectionType.QueuedConnection)
        self.poller.start()

    def _build_menu(self):
        menu = QMenu()
        refresh = QAction("Refresh now", menu)
        refresh.triggered.connect(lambda: self.poller.refresh())
        style_menu = menu.addMenu("Icon style")
        group = QActionGroup(style_menu)
        for style, label in (("battery", "Battery"), ("number", "Large number")):
            action = QAction(label, style_menu, checkable=True)
            action.setChecked(style == self.style)
            action.triggered.connect(lambda _=False, s=style: self._set_style(s))
            group.addAction(action)
            style_menu.addAction(action)
        self.autostart = QAction("Start with Windows", menu, checkable=True)
        self.autostart.setChecked(startup.is_enabled())
        self.autostart.toggled.connect(self._toggle_autostart)
        quit_ = QAction("Quit", menu)
        quit_.triggered.connect(self._quit)
        menu.insertAction(style_menu.menuAction(), refresh)
        menu.addAction(self.autostart)
        menu.addSeparator()
        menu.addAction(quit_)
        self.menu = menu            # keep a reference; Qt doesn't own it
        self.tray.setContextMenu(menu)

    def _first_run_autostart(self):
        if not self.settings.get("autostart_initialized"):
            startup.set_enabled(True)
            self.settings.set("autostart_initialized", True)
        else:
            startup.refresh()
        self.autostart.setChecked(startup.is_enabled())

    def _set_style(self, style: str):
        self.style = style
        self.settings.set("icon_style", style)
        self._set_icon(self.icon_state)

    def _toggle_autostart(self, on: bool):
        try:
            startup.set_enabled(on)
        except OSError as e:
            log.warning("Couldn't change startup entry: %s", e)
        self.autostart.setChecked(startup.is_enabled())

    def _quit(self):
        self.poller.stop()
        self.tray.hide()
        QApplication.quit()

    # -- updates -------------------------------------------------------------

    def _on_reading(self, reading):
        now = time.time()
        self.snap = snap = self.tracker.update(reading, now)
        if self.tracker.pending is not None:
            self.poller.expedite()
        self._save_state(now)

        theme = taskbar_theme()
        if theme != self.theme:
            self.theme, self.icon_key = theme, None

        if snap.status == device.OK:
            state = IconState("level", snap.level, snap.charging)
        elif snap.status == device.NO_DONGLE:
            state = IconState("no_dongle")
        else:
            state = IconState("off")
        self._set_icon(state)
        self.tray.setToolTip(text.tooltip(snap, now))
        if self.card.isVisible():
            self.card.show_snapshot(snap, self.theme, now)

        key = (snap.status, snap.raw_level, snap.level, snap.charging, snap.unstable)
        if key != self.log_key:
            log.info("raw=%s shown=%s charging=%s unstable=%s rate=%s",
                     reading.level if reading.status == device.OK else reading.status,
                     snap.level, snap.charging, snap.unstable,
                     f"{snap.rate_per_hour:.1f}" if snap.rate_per_hour else None)
            self.log_key = key

    def _save_state(self, now: float):
        # On change, and once a minute so the timestamp stays fresh enough to
        # resume from; not every poll, to keep disk writes rare.
        state = self.tracker.saved_state(now)
        if state is None:
            return
        key = (state["level"], state["charging"])
        if key != self.saved_key or now - self.saved_at > 60:
            self.settings.set("last_state", state)
            self.saved_key, self.saved_at = key, now

    def _set_icon(self, state: IconState):
        self.icon_state = state
        key = (state, self.theme, self.style)
        if key != self.icon_key:
            self.tray.setIcon(make_icon(state, self.theme, self.style))
            self.icon_key = key

    def _on_activated(self, reason):
        if reason != QSystemTrayIcon.ActivationReason.Trigger:
            return
        if self.card.isVisible():
            self.card.hide()
            return
        # The click that closed the popup also lands here; don't reopen it.
        if time.monotonic() - self.card.closed_at < 0.35:
            return
        now = time.time()
        snap = self.snap or self.tracker.snapshot(now)
        self.card.show_snapshot(snap, self.theme, now)
        anchor = self.tray.geometry()
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        self.card.open_near(anchor, screen.availableGeometry())


def _setup_logging():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA_DIR / "app.log", maxBytes=256_000, backupCount=1,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    sys.excepthook = lambda *exc: log.critical("Uncaught exception", exc_info=exc)


def _claim_single_instance():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def main():
    _setup_logging()
    mutex = _claim_single_instance()
    if mutex is None:
        log.info("Already running; exiting")
        return
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setApplicationName("Arctis Battery")
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("No system tray available")
        return
    log.info("Starting")
    app = App()  # noqa: F841  (kept alive for the event loop)
    sys.exit(qapp.exec())
