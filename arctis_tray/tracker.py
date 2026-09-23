"""Turn raw battery readings into what the UI shows: a steady level, whether
the headset is charging, and rate / time-left estimates.

The headset has no charging flag. It estimates charge from battery voltage,
and a charger lifts that voltage, so the reported level jumps about 4-5 points
the moment a charger starts delivering current and drops the same amount when
it stops (measured: 57 -> 61 -> 62 on plug-in; 62 -> 57, 73 -> 68, 75 -> 70
on unplug). That jump is the primary charging signal. A sustained rise or fall
without a jump is the fallback, for when charging began while the app wasn't
watching.

The jump is also an error: while charging, the reported level reads high by
that offset. The shown level subtracts it, so plugging in or unplugging
doesn't make the number leap. Charging current (and so the offset) tapers
toward full, so the subtracted amount fades linearly to zero at 100%, where
the headset's own reading is right again. That fade is a model, not a
measurement; unplug drops at different levels are recorded to check it.
"""
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import statistics

from . import device

JUMP = 3                  # points between steady readings that mean plug/unplug
TREND_RISE = 3            # sustained rise without a jump that means charging
TREND_FALL = 2            # sustained fall while 'charging' that means it stopped
SETTLE_S = 30             # after a plug/unplug the reading keeps moving this long
UNSTABLE_WINDOW_S = 5 * 60
UNSTABLE_TRANSITIONS = 3  # this many plug/unplug flips in the window
ERROR_GRACE_S = 60        # keep showing the last level through brief read errors
RATE_WINDOW_S = 3 * 3600
MIN_DRAIN_SPAN_H = 0.5
# Edge times are precise to the gauge's ~12-15 s update cycle, so a few
# minutes of charging already gives a rate within about 5%.
MIN_CHARGE_SPAN_H = 4 / 60
MIN_LEARN_DRAIN_H = 1.0
TAPER_FROM = 80           # lithium charging slows for the last stretch
TAPER_FACTOR = 0.5
RESUME_WINDOW_S = 10 * 60  # restore charging state after a restart this quick
DEFAULT_OFFSET = 5.0       # until an unplug has been measured
MAX_OFFSET = 10

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Snapshot:
    status: str
    level: int | None = None                 # shown (offset-corrected) level
    raw_level: int | None = None             # what the headset reports
    charging: bool = False
    full: bool = False
    rate_per_hour: float | None = None       # negative while draining
    hours_left: float | None = None          # to empty, or to full while charging
    typical_charge_per_hour: float | None = None
    stopped_at: float | None = None          # charging ended before full
    unstable: bool = False
    last_ok: float | None = None


class LearnedRates:
    """Drain rate, charge rates, and charging offsets remembered across runs,
    so estimates don't start from scratch after a reboot."""

    def __init__(self, path: Path | None):
        self.path = path
        self.drain_per_hour: float | None = None
        self.charge_rates: list[float] = []
        self.offsets: list[list[float]] = []   # [raw level before unplug, drop]
        if path and path.exists():
            try:
                data = json.loads(path.read_text())
                self.drain_per_hour = data.get("drain_per_hour")
                self.charge_rates = data.get("charge_rates", [])[-5:]
                self.offsets = data.get("offsets", [])[-20:]
            except (OSError, ValueError) as e:
                log.warning("Couldn't load %s: %s", path, e)

    @property
    def typical_charge_per_hour(self) -> float | None:
        return statistics.median(self.charge_rates) if self.charge_rates else None

    @property
    def typical_offset(self) -> float:
        return statistics.median(d for _, d in self.offsets) if self.offsets else DEFAULT_OFFSET

    def add_drain(self, rate: float):
        old = self.drain_per_hour
        self.drain_per_hour = rate if old is None else old * 0.7 + rate * 0.3
        self._save()

    def add_charge(self, rate: float):
        self.charge_rates = (self.charge_rates + [rate])[-5:]
        self._save()

    def add_offset(self, level: int, drop: int):
        self.offsets = (self.offsets + [[level, drop]])[-20:]
        self._save()

    def _save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({
                "drain_per_hour": self.drain_per_hour,
                "charge_rates": self.charge_rates,
                "offsets": self.offsets,
            }))
        except OSError as e:
            log.warning("Couldn't save %s: %s", self.path, e)


def _edge_rate(edges, min_span_h):
    """Points per hour between the first and last level change. Measuring
    between changes (not raw samples) avoids 1%-quantization bias."""
    if len(edges) < 2:
        return None
    (t0, l0), (t1, l1) = edges[0], edges[-1]
    span_h = (t1 - t0) / 3600
    if abs(l1 - l0) < 2 or span_h < min_span_h:
        return None
    return (l1 - l0) / span_h


class Tracker:
    def __init__(self, learned: LearnedRates | None = None):
        self.learned = learned or LearnedRates(None)
        self.status: str | None = None
        self.level: int | None = None          # raw, as reported
        self.pending: int | None = None
        self.charging = False
        self.edges: list[tuple[float, int]] = []
        self.seg_min = self.seg_max = None
        self.transitions: list[float] = []
        self.stopped_at: float | None = None
        self.last_ok: float | None = None
        self._resume: dict | None = None
        self._clear_offset()

    def _clear_offset(self):
        self.offset = 0.0         # points subtracted at offset_ref
        self.offset_ref = None    # raw level the offset was measured at
        self.floor = None         # shown level never drops below this while charging
        self.plug = None          # (time, raw level before plug-in) while settling
        self.unplug = None        # (time, raw level before unplug) while settling

    def resume_from(self, saved: dict | None, now: float):
        """Carry state across a quick restart (an update, a crash): the
        plug-in jump that revealed charging won't happen again, and the
        level history behind the rate estimate would take minutes to rebuild."""
        if saved and now - saved.get("t", 0) < RESUME_WINDOW_S:
            self._resume = saved

    def saved_state(self, now: float) -> dict | None:
        if self.status != device.OK or self.level is None:
            return None
        return {"t": now, "level": self.level, "charging": self.charging,
                "offset": self.offset, "offset_ref": self.offset_ref, "floor": self.floor,
                "edges": [list(e) for e in self.edges[-100:]]}

    # -- input ---------------------------------------------------------------

    def update(self, reading: device.Reading, now: float) -> Snapshot:
        if reading.status == device.OK:
            self.status = device.OK
            self.last_ok = now
            self._on_level(reading.level, now)
            self._settle(now)
            if self.charging:
                self.floor = max(self.floor or 0, self._shown())
        elif reading.status == device.ERROR:
            # One failed read is usually another app briefly holding the
            # device; keep the last level unless it keeps failing.
            if self.last_ok is None or now - self.last_ok > ERROR_GRACE_S:
                self._reset(device.ERROR)
        else:
            self._reset(reading.status, now)
        return self.snapshot(now)

    def _reset(self, status, now=None):
        if now is not None:
            self._end_segment()
        self.status = status
        self.level = self.pending = None
        self.charging = False
        self.edges, self.transitions = [], []
        self.stopped_at = None
        self._clear_offset()

    def _on_level(self, raw: int, now: float):
        if self.level is None:
            self.level = raw
            saved, self._resume = self._resume, None
            resumed = False
            if saved and saved.get("charging"):
                # Still charging only if the level is where charging would leave it.
                if saved["level"] - 1 <= raw <= saved["level"] + 5:
                    resumed = self.charging = True
                    # A state saved without an offset (older version) is treated
                    # like trend-found charging: learned offset, number held.
                    self.offset = saved.get("offset") or self.learned.typical_offset
                    self.offset_ref = saved.get("offset_ref") or raw
                    self.floor = saved.get("floor") or raw
            elif saved:
                resumed = saved["level"] - 2 <= raw <= saved["level"] + 1
            self._new_segment()
            if resumed:
                self.edges = [(t, lvl) for t, lvl in saved.get("edges", [])]
                levels = [lvl for _, lvl in self.edges] + [raw]
                self.seg_min, self.seg_max = min(levels), max(levels)
            return
        if raw == self.level:
            self.pending = None
        elif abs(raw - self.level) >= JUMP:
            # Plug/unplug: far bigger than the gauge's bounce, so there's
            # nothing to confirm, and waiting would only delay the icon.
            self.pending = None
            self._accept(raw, now)
        elif self.pending is not None and (raw > self.level) == (self.pending > self.level):
            # Two readings in a row moved the same way: accept. This filters
            # the 1-point bounce voltage-based gauges produce.
            self.pending = None
            self._accept(raw, now)
        else:
            self.pending = raw

    def _accept(self, new: int, now: float):
        old, self.level = self.level, new
        delta = new - old
        # While a plug/unplug settles, creep in its direction is part of the
        # jump (see _settle); a jump the other way is a real reversal, which a
        # flaky cable produces within seconds.
        if self.plug and delta > -JUMP:
            return
        if self.unplug and delta < JUMP:
            return
        if delta >= JUMP:
            if not self.charging:
                self._set_charging(True, now, before=old)
            else:
                self._new_segment()
        elif delta <= -JUMP:
            if self.charging:
                self._set_charging(False, now, before=old)
            else:
                self._new_segment()
        else:
            self.edges.append((now, new))
            self.seg_min = min(self.seg_min, new)
            self.seg_max = max(self.seg_max, new)
            if not self.charging and new - self.seg_min >= TREND_RISE:
                self._set_charging(True, now)
            elif self.charging and self.seg_max - new >= TREND_FALL:
                self._set_charging(False, now)

    def _set_charging(self, on: bool, now: float, before: int | None = None):
        reached_full = self.seg_max == 100
        shown_before = self._shown()
        self._end_segment()
        self.charging = on
        self.transitions = [t for t in self.transitions if now - t < UNSTABLE_WINDOW_S]
        self.transitions.append(now)
        # Ending at 100% is a finished charge, not an interruption.
        self.stopped_at = None if on or reached_full or self.level >= 100 else now
        self._clear_offset()
        if on:
            if before is not None:
                # Seen plugging in: the jump is the offset. It's refined while
                # the reading settles, so the shown level holds where it was.
                self.plug = (now, before)
                self.offset, self.offset_ref = self.level - before, self.level
                self.floor = before
            else:
                # Charging found by trend, so the reading was already inflated.
                # Subtract the learned offset, but hold the number steady
                # instead of letting it drop now that charging's been noticed.
                self.offset, self.offset_ref = self.learned.typical_offset, self.level
                self.floor = shown_before
        elif before is not None:
            self.unplug = (now, before)
        self._new_segment()

    def _settle(self, now: float):
        """Plug and unplug jumps keep creeping for a few seconds (57 -> 61 ->
        62; 75 -> 70 -> 69). Track them to the end before trusting the level."""
        if self.plug:
            t, before = self.plug
            if self.level - before > self.offset:
                self.offset = float(min(MAX_OFFSET, self.level - before))
                self.offset_ref = self.level
            if now - t >= SETTLE_S:
                self.plug = None
                self._new_segment()
        if self.unplug:
            t, before = self.unplug
            if now - t >= SETTLE_S:
                self.unplug = None
                drop = before - self.level
                if JUMP <= drop <= MAX_OFFSET:
                    self.learned.add_offset(before, drop)
                    log.info("Charging offset at %d%%: %d points", before, drop)
                self._new_segment()

    def _new_segment(self):
        self.edges = []
        self.seg_min = self.seg_max = self.level

    def _end_segment(self):
        if self.charging:
            below_taper = [e for e in self.edges if e[1] <= TAPER_FROM]
            rate = _edge_rate(below_taper, MIN_CHARGE_SPAN_H)
            if rate and rate > 0:
                self.learned.add_charge(rate)
        else:
            rate = _edge_rate(self.edges, MIN_LEARN_DRAIN_H)
            if rate and rate < 0:
                self.learned.add_drain(-rate)
        self.edges = []

    # -- output --------------------------------------------------------------

    def _fade_span(self) -> float:
        return max(1.0, 100.0 - self.offset_ref)

    def _shown(self) -> int:
        """The raw level minus the charging offset, which fades linearly to
        zero between where it was measured and 100%."""
        if self.level is None or not self.charging or not self.offset:
            return self.level
        if self.level >= 100:
            return 100
        fade = min(1.0, max(0.0, (100 - self.level) / self._fade_span()))
        shown = round(self.level - self.offset * fade)
        return max(self.floor or 0, min(100, shown))

    def _current_rate(self, now: float) -> float | None:
        edges = [e for e in self.edges if now - e[0] <= RATE_WINDOW_S]
        min_span = MIN_CHARGE_SPAN_H if self.charging else MIN_DRAIN_SPAN_H
        rate = _edge_rate(edges, min_span)
        if rate is None or (rate > 0) != self.charging:
            return None
        # If the next change is overdue, the rate has slowed since the last
        # one; measure to now instead so the estimate doesn't stay optimistic.
        (t0, l0), (t1, _) = edges[0], edges[-1]
        step_s = (t1 - t0) / abs(self.level - l0)
        if now - t1 > 2 * step_s:
            rate = (self.level - l0) / ((now - t0) / 3600)
        return rate

    def snapshot(self, now: float) -> Snapshot:
        if self.status != device.OK or self.level is None:
            return Snapshot(self.status or device.ERROR, last_ok=self.last_ok)

        rate = self._current_rate(now)
        typical = self.learned.typical_charge_per_hour
        full = self.charging and self.level >= 100
        hours = None
        if self.charging and not full:
            # Rates and times run on the raw level: it reaches 100 at the same
            # moment the shown level does.
            r = rate or typical
            if r:
                # A rate measured before the taper runs at full speed until
                # TAPER_FROM, then slower; one measured inside it already is.
                measured_in_taper = bool(self.edges) and self.edges[0][1] >= TAPER_FROM
                fast = max(0, TAPER_FROM - self.level) / r
                slow_rate = r if measured_in_taper else r * TAPER_FACTOR
                slow = (100 - max(self.level, TAPER_FROM)) / slow_rate
                hours = fast + slow
            # The shown level climbs faster than the raw one as the offset
            # fades, so report rates in shown points.
            if self.offset:
                scale = 1 + self.offset / self._fade_span()
                rate = rate * scale if rate else None
                typical = typical * scale if typical else None
        elif not self.charging:
            r = -rate if rate else self.learned.drain_per_hour
            if r:
                hours = self.level / r
                rate = -r

        return Snapshot(
            status=device.OK,
            level=self._shown(),
            raw_level=self.level,
            charging=self.charging,
            full=full,
            rate_per_hour=rate if not full else None,
            hours_left=hours,
            typical_charge_per_hour=typical,
            stopped_at=self.stopped_at,
            unstable=len([t for t in self.transitions
                          if now - t < UNSTABLE_WINDOW_S]) >= UNSTABLE_TRANSITIONS,
            last_ok=self.last_ok,
        )
