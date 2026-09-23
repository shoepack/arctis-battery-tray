"""Start-with-Windows via the per-user Run key (no admin rights needed; shows
up in Task Manager's Startup tab where it can also be turned off)."""
from pathlib import Path
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "ArctisBatteryTray"


def command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # Running from source: use pythonw so no console window appears.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    main = Path(__file__).resolve().parents[1] / "run.pyw"
    return f'"{pythonw}" "{main}"'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE)
            return True
    except FileNotFoundError:
        return False


def set_enabled(on: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, VALUE)
            except FileNotFoundError:
                pass


def refresh():
    """Point an existing entry at the current location, in case the app moved."""
    if is_enabled():
        set_enabled(True)
