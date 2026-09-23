import pytest

from arctis_tray import device
from arctis_tray.tracker import LearnedRates, Tracker

POLL = 5


class Sim:
    """Feeds a tracker one reading per poll interval."""

    def __init__(self, tracker=None):
        self.tr = tracker or Tracker()
        self.t = 1_000_000.0
        self.snap = None

    def read(self, level=None, status=device.OK):
        self.snap = self.tr.update(device.Reading(status, level), self.t)
        self.t += POLL
        return self.snap

    def hold(self, level, seconds):
        for _ in range(max(1, int(seconds // POLL))):
            self.read(level)
        return self.snap

    def ramp(self, start, stop, seconds_per_point):
        step = 1 if stop > start else -1
        for level in range(start, stop + step, step):
            self.hold(level, seconds_per_point)
        return self.snap


def test_first_reading_is_shown_immediately():
    s = Sim()
    snap = s.read(57)
    assert snap.level == 57 and not snap.charging


def test_one_point_bounce_is_ignored():
    s = Sim()
    s.hold(57, 30)
    s.read(58)
    snap = s.read(57)
    assert snap.level == 57


def test_real_one_point_drop_is_accepted_after_two_reads():
    s = Sim()
    s.hold(57, 30)
    assert s.read(56).level == 57
    assert s.read(56).level == 56


def test_plug_in_jump_starts_charging_on_the_first_read():
    # Measured on the real headset: 57 -> 61 -> 62 right after plugging in.
    s = Sim()
    s.hold(57, 60)
    snap = s.read(61)
    assert snap.charging and snap.raw_level == 61


def test_unplug_drop_stops_charging_and_records_time():
    s = Sim()
    s.hold(57, 60)
    s.hold(62, 60)
    assert s.snap.charging
    stop_time = s.t
    snap = s.read(57)
    assert not snap.charging
    assert snap.stopped_at == pytest.approx(stop_time)


def test_unplugging_a_full_headset_is_not_an_interruption():
    s = Sim()
    s.hold(90, 60)
    s.hold(95, 60)           # plug in
    s.ramp(95, 100, 60)
    assert s.snap.full
    s.hold(96, 60)           # unplug
    assert not s.snap.charging
    assert s.snap.stopped_at is None


def test_flaky_cable_is_flagged_unstable():
    s = Sim()
    s.hold(57, 30)
    for _ in range(2):
        s.hold(62, 30)
        s.hold(57, 30)
    assert s.snap.unstable


def test_single_plug_in_is_not_unstable():
    s = Sim()
    s.hold(57, 30)
    s.hold(62, 30)
    assert not s.snap.unstable


def test_drain_estimate_needs_enough_history():
    s = Sim()
    s.ramp(80, 79, 15 * 60)
    assert s.snap.hours_left is None


def test_drain_rate_and_time_remaining():
    s = Sim()
    s.ramp(80, 76, 15 * 60)         # 4 %/h
    snap = s.snap
    assert snap.rate_per_hour == pytest.approx(-4, rel=0.1)
    assert snap.hours_left == pytest.approx(76 / 4, rel=0.1)


def test_stalled_drain_slows_the_estimate():
    s = Sim()
    s.ramp(80, 76, 15 * 60)
    s.hold(76, 2 * 3600)            # no change for two hours: drain has slowed
    assert abs(s.snap.rate_per_hour) < 2


def test_charge_estimate_accounts_for_the_taper():
    s = Sim()
    s.hold(40, 60)
    s.hold(45, 60)                  # plug in
    s.ramp(45, 52, 3 * 60)          # 20 %/h raw
    snap = s.snap
    # The shown level climbs faster as the 5-point offset fades over 55 points.
    assert snap.rate_per_hour == pytest.approx(20 * (1 + 5 / 55), rel=0.05)
    # 28 points at 20 %/h to 80%, then 20 points at half speed.
    assert snap.hours_left == pytest.approx(28 / 20 + 20 / 10, rel=0.1)


def test_charging_seen_by_trend_when_started_before_the_app():
    s = Sim()
    s.hold(60, 30)
    s.ramp(60, 63, 4 * 60)
    assert s.snap.charging
    # The reading was already inflated; the number holds rather than drops.
    assert s.snap.level == 63


# -- charging offset --------------------------------------------------------

def test_shown_level_holds_through_plug_in():
    s = Sim()
    s.hold(57, 60)
    s.read(61)
    s.read(62)                      # the jump keeps creeping, as measured
    snap = s.hold(62, 60)
    assert snap.charging and snap.raw_level == 62 and snap.level == 57


def test_shown_level_is_continuous_through_unplug():
    s = Sim()
    s.hold(57, 60)
    s.hold(62, 60)                  # plug in, offset 5
    s.ramp(62, 70, 3 * 60)
    before = s.snap.level
    snap = s.hold(65, 60)           # unplug drops the reading by 5
    assert not snap.charging
    assert abs(snap.level - before) <= 1


def test_shown_level_reaches_100_with_the_headset():
    s = Sim()
    s.hold(57, 60)
    s.hold(62, 60)
    snap = s.ramp(62, 100, 60)
    assert snap.level == 100 and snap.full


def test_shown_level_never_drops_while_charging():
    s = Sim()
    s.hold(57, 60)
    s.hold(62, 60)
    s.ramp(62, 70, 3 * 60)
    peak = s.snap.level
    s.hold(69, 30)                  # 1-point bounce
    assert s.snap.charging and s.snap.level >= peak


def test_unplug_drop_is_learned_as_the_offset(tmp_path):
    path = tmp_path / "learned.json"
    s = Sim(Tracker(LearnedRates(path)))
    s.hold(57, 60)
    s.hold(62, 60)
    s.hold(57, 60)                  # unplug, then settle
    assert LearnedRates(path).offsets == [[62, 5]]


def test_trend_detected_charging_uses_the_learned_offset(tmp_path):
    path = tmp_path / "learned.json"
    LearnedRates(path).add_offset(70, 4)
    s = Sim(Tracker(LearnedRates(path)))
    s.hold(60, 30)
    s.ramp(60, 63, 4 * 60)
    assert s.tr.offset == 4


def test_unplug_seconds_after_plug_in_is_still_seen():
    s = Sim()
    s.hold(57, 30)
    s.read(62)
    s.read(62)
    snap = s.hold(57, 10)
    assert not snap.charging


def test_small_recovery_after_unplug_is_not_charging():
    s = Sim()
    s.hold(57, 60)
    s.ramp(57, 59, 5 * 60)          # voltage settling, +2
    assert not s.snap.charging


def test_headset_off_resets_state():
    s = Sim()
    s.hold(57, 30)
    s.hold(62, 30)
    snap = s.read(status=device.HEADSET_OFF)
    assert snap.status == device.HEADSET_OFF and snap.level is None


def test_brief_errors_keep_the_last_level():
    s = Sim()
    s.hold(57, 30)
    snap = s.read(status=device.ERROR)
    assert snap.status == device.OK and snap.level == 57
    for _ in range(15):             # 75 s of errors
        snap = s.read(status=device.ERROR)
    assert snap.status == device.ERROR


def test_charging_state_survives_a_quick_restart():
    s = Sim()
    s.hold(57, 30)
    s.hold(62, 30)
    saved = s.tr.saved_state(s.t)

    fresh = Sim()
    fresh.t = s.t + 60
    fresh.tr.resume_from(saved, fresh.t)
    snap = fresh.read(62)
    assert snap.charging and snap.level == 57       # offset carried over too


def test_time_to_full_appears_after_a_few_minutes():
    s = Sim()
    s.hold(57, 60)
    s.hold(62, 60)                  # plug in
    assert s.snap.hours_left is None
    snap = s.ramp(62, 66, 2 * 60)   # 30 %/h raw, about 8 min
    assert snap.hours_left is not None


def test_rate_history_survives_a_quick_restart():
    s = Sim()
    s.hold(57, 60)
    s.hold(62, 60)
    s.ramp(62, 68, 2 * 60)
    saved = s.tr.saved_state(s.t)

    fresh = Sim()
    fresh.t = s.t + 30
    fresh.tr.resume_from(saved, fresh.t)
    snap = fresh.read(68)
    assert snap.charging and snap.hours_left is not None


def test_drain_history_survives_a_quick_restart():
    s = Sim()
    s.ramp(80, 76, 15 * 60)
    saved = s.tr.saved_state(s.t)

    fresh = Sim()
    fresh.t = s.t + 30
    fresh.tr.resume_from(saved, fresh.t)
    snap = fresh.read(76)
    assert not snap.charging
    assert snap.rate_per_hour == pytest.approx(-4, rel=0.15)


def test_stale_or_mismatched_saved_state_is_ignored():
    s = Sim()
    s.hold(57, 30)
    s.hold(62, 30)
    saved = s.tr.saved_state(s.t)

    later = Sim()
    later.t = s.t + 3600
    later.tr.resume_from(saved, later.t)
    assert not later.read(62).charging

    unplugged = Sim()
    unplugged.t = s.t + 60
    unplugged.tr.resume_from(saved, unplugged.t)
    assert not unplugged.read(57).charging      # dropped: charger came off


def test_learned_drain_survives_restart(tmp_path):
    path = tmp_path / "learned.json"
    s = Sim(Tracker(LearnedRates(path)))
    s.ramp(80, 74, 15 * 60)         # 1.5 h at 4 %/h
    s.read(status=device.HEADSET_OFF)
    assert path.exists()

    fresh = Sim(Tracker(LearnedRates(path)))
    snap = fresh.read(60)
    assert snap.hours_left == pytest.approx(60 / 4, rel=0.1)


def test_typical_charge_rate_is_learned(tmp_path):
    path = tmp_path / "learned.json"
    s = Sim(Tracker(LearnedRates(path)))
    s.hold(40, 60)
    s.hold(45, 60)
    s.ramp(45, 55, 3 * 60)          # 20 %/h
    s.hold(50, 60)                  # unplug
    assert LearnedRates(path).typical_charge_per_hour == pytest.approx(20, rel=0.1)
