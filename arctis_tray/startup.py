"""Start-with-Windows via the per-user Run key (no admin rights needed; shows
up in Task Manager's Startup tab where it can also be turned off).

A Run entry alone isn't enough on current Windows 11: at sign-in Explorer
skipped ours every time (16 sign-ins, never launched) while launching every
entry that had an approval record under StartupApproved\\Run. That record is
what Task Manager and Settings > Apps > Startup write when you switch an app
on (first byte 02) or off (03), so it's written alongside the Run entry. A
user's "off" there is respected rather than overwritten.
"""
from pathlib import Path
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
VALUE = "ArctisBatteryTray"
APPROVED_ON = bytes([0x02] + [0x00] * 11)


def argv() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    # Running from source: use pythonw so no console window appears.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    main = Path(__file__).resolve().parents[1] / "run.pyw"
    return [str(pythonw), str(main)]


def command() -> str:
    return " ".join(f'"{a}"' for a in argv())


def _read(key_path: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            return winreg.QueryValueEx(k, VALUE)[0]
    except FileNotFoundError:
        return None


def _approval():
    """None if Windows has no record; True/False for switched on/off."""
    data = _read(APPROVED_KEY)
    if not data:
        return None
    return data[0] % 2 == 0          # 02 on, 03 off (Task Manager's encoding)


def _write_approval(on: bool):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, VALUE, 0, winreg.REG_BINARY, APPROVED_ON)
        else:
            try:
                winreg.DeleteValue(k, VALUE)
            except FileNotFoundError:
                pass


def is_enabled() -> bool:
    return _read(RUN_KEY) is not None and _approval() is not False


def set_enabled(on: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, VALUE)
            except FileNotFoundError:
                pass
    _write_approval(on)


def refresh():
    """On each launch: point the entry at the current location in case the
    app moved, and add the approval record installs before it was written
    are missing. Leaves it alone if the user switched it off in Windows."""
    if _read(RUN_KEY) is not None and _approval() is None:
        set_enabled(True)
    elif is_enabled():
        set_enabled(True)
