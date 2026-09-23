"""Probe the Arctis 7 dongle: send the battery request and dump the raw reply."""
import sys
import time

import hid

VID, PID = 0x1038, 0x12AD
BATTERY_REQUEST = [0x06, 0x18]


def probe(usage_page):
    for d in hid.enumerate(VID, PID):
        if d["usage_page"] != usage_page:
            continue
        dev = hid.device()
        dev.open_path(d["path"])
        try:
            dev.write(BATTERY_REQUEST + [0] * 6)
            reply = dev.read(64, timeout_ms=1000)
        finally:
            dev.close()
        return reply
    return None


if __name__ == "__main__":
    samples = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    for i in range(samples):
        for page in (0xFF43, 0xFF00):
            reply = probe(page)
            hexed = " ".join(f"{b:02x}" for b in reply) if reply else "(no reply)"
            print(f"{time.strftime('%H:%M:%S')} page {page:#06x}: {hexed}")
        if i < samples - 1:
            time.sleep(2)
