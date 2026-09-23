"""User-facing wording for the card and tooltip, kept in one place so the two
always agree."""
import time

from . import device

NAME = "Arctis 7"


def duration(hours: float) -> str:
    minutes = hours * 60
    if minutes < 5:
        return "under 5 min"
    if minutes < 60:
        return f"{int(round(minutes / 5) * 5)} min"
    if hours < 10:
        h, m = divmod(int(round(minutes / 10) * 10), 60)
        return f"{h} h {m} min" if m else f"{h} h"
    return f"{round(hours)} h"


def clock(ts: float) -> str:
    return time.strftime("%I:%M %p", time.localtime(ts)).lstrip("0")


def updated_ago(seconds: float) -> str:
    if seconds < 90:
        return f"updated {int(seconds)} s ago"
    return f"updated {int(seconds // 60)} min ago"


def status_line(snap, now: float) -> str:
    if snap.status == device.HEADSET_OFF:
        return "Headset off"
    if snap.status == device.NO_DONGLE:
        return "Dongle not connected"
    if snap.status != device.OK:
        return "Can't read the headset"
    if snap.unstable:
        return "Connection unstable · check the cable"
    if snap.full:
        return "Fully charged"
    if snap.charging:
        if snap.hours_left is not None:
            return f"Charging · full in about {duration(snap.hours_left)}"
        return "Charging · estimating time to full"
    if snap.stopped_at:
        return f"Charging stopped at {clock(snap.stopped_at)}"
    if snap.hours_left is not None:
        return f"About {duration(snap.hours_left)} remaining"
    return "Estimating time remaining"


def rate_line(snap) -> str:
    if snap.status != device.OK or snap.full:
        return ""
    if snap.charging:
        parts = []
        if snap.rate_per_hour:
            parts.append(f"+{snap.rate_per_hour:.0f}% per hour")
        typical = snap.typical_charge_per_hour
        # Only compare before the taper; the last stretch is always slower.
        if typical and snap.level <= 85:
            parts.append(f"usually +{typical:.0f}%" if parts else f"Usually +{typical:.0f}% per hour")
        return " · ".join(parts)
    parts = []
    if snap.stopped_at and snap.hours_left is not None:
        parts.append(f"About {duration(snap.hours_left)} remaining")
    if snap.rate_per_hour:
        parts.append(f"−{abs(snap.rate_per_hour):.1f}% per hour")
    return " · ".join(parts)


def unavailable_detail(snap) -> str:
    return {
        device.HEADSET_OFF: "Turn on the headset to see its battery.",
        device.NO_DONGLE: "Plug in the USB dongle.",
    }.get(snap.status, "Retrying every few seconds.")


def tooltip(snap, now: float) -> str:
    if snap.status != device.OK:
        return f"{NAME} · {status_line(snap, now).lower()}"
    line = status_line(snap, now)
    tip = f"{NAME} · {snap.level}% · {line[0].lower()}{line[1:]}"
    return tip[:127]
