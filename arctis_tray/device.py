"""Read the Arctis 7 battery level from its USB dongle.

The dongle answers a two-byte HID request (06 18) on its 0xFF43 vendor
collection. The reply echoes the request and byte 2 is the battery percent.
The headset reports no charging flag; see tracker.py for how that's inferred.
"""
from dataclasses import dataclass
import logging

import hid

VID, PID = 0x1038, 0x12AD
USAGE_PAGE = 0xFF43
BATTERY_REQUEST = [0x06, 0x18, 0, 0, 0, 0, 0, 0]
READ_TIMEOUT_MS = 1000

log = logging.getLogger(__name__)

OK = "ok"
HEADSET_OFF = "off"
NO_DONGLE = "no_dongle"
ERROR = "error"


@dataclass(frozen=True)
class Reading:
    status: str
    level: int | None = None


def _dongle_path():
    for d in hid.enumerate(VID, PID):
        if d["usage_page"] == USAGE_PAGE:
            return d["path"]
    return None


def read_battery() -> Reading:
    """Query the dongle once. Opens and closes the device every call, so an
    unplug, replug, or sleep/resume never leaves a stale handle behind."""
    path = _dongle_path()
    if path is None:
        return Reading(NO_DONGLE)

    dev = hid.device()
    try:
        dev.open_path(path)
        dev.write(BATTERY_REQUEST)
        reply = dev.read(32, timeout_ms=READ_TIMEOUT_MS)
    except OSError as e:
        log.warning("HID read failed: %s", e)
        return Reading(ERROR)
    finally:
        try:
            dev.close()
        except Exception:
            pass

    # No reply, a reply that isn't ours, or a 0% level all mean the dongle is
    # present but the headset isn't answering (a live headset can't report 0).
    if len(reply) < 3 or reply[0] != 0x06 or reply[1] != 0x18 or reply[2] == 0:
        return Reading(HEADSET_OFF)
    return Reading(OK, min(reply[2], 100))
