"""Live readout of the raw battery level every 0.5 s, for timing how fast the
headset's reported level reacts to plugging/unplugging a charger."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arctis_tray import device

LOG = Path(__file__).with_name("watch_log.txt")

if __name__ == "__main__":
    print("Reading the headset every 0.5 s. Unplug / plug the charger and watch the")
    print("level column. Changes are marked with <<<. Close this window when done.\n")
    last = None
    start = time.time()
    with LOG.open("w") as log:
        while True:
            r = device.read_battery()
            value = r.level if r.status == device.OK else r.status
            stamp = time.strftime("%H:%M:%S") + f".{int(time.time() % 1 * 10)}"
            mark = "   <<< changed" if last is not None and value != last else ""
            line = f"{stamp}   level {value}{mark}"
            if mark or int(time.time() - start) % 5 == 0:
                print(line, flush=True)
            log.write(line + "\n")
            log.flush()
            last = value
            time.sleep(0.5)
