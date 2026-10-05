"""Manual check of the hang watchdog: run the tray app from source (without
the supervisor), then freeze its UI thread after a few readings. Expect
hang.log to get stack dumps every 10 s and the process to exit with code 3
after ~90 s; under the supervisor, that exit triggers a restart.
Quit any running copy first."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arctis_tray import app

original = app.App._on_reading
calls = 0


def freezing_on_reading(self, reading):
    global calls
    calls += 1
    original(self, reading)
    if calls == 5:
        app.log.warning("test_hang: freezing the UI thread")
        time.sleep(600)


app.App._on_reading = freezing_on_reading
app._setup_logging("app.log")
app._run_tray_app()
