#!/usr/bin/env python
"""Pick the ROTATING subset of admin forms this iteration should inspect
(ticket T3 / #14).

The AFK loop must not re-check the same form forever - coverage should broaden
across runs. This reads the form pool seed_synthetic_dataset.py wrote and returns
a sliding window over it, advanced on TWO axes so the subset varies both:

  * across days   - by UTC day-of-year, so each daily /schedule fire (T4 / #15)
                    starts on a different slice;
  * within a day  - by a per-window counter file ($AFK_ROTATION_COUNTER, default
                    /tmp/afk_rotation_counter), bumped every call, so the many
                    back-to-back iterations inside one usage window each advance.

window index = (UTC day-of-year + counter) ; the K forms starting at
index*K (mod pool size) are chosen, then the counter is incremented. Over enough
iterations every form in the pool is visited - coverage accumulates instead of
re-checking one form.

    python .sandcastle/pick_rotation_subset.py [K]     # K defaults to 8

Prints one tab-separated line per chosen form: kind<TAB>url<TAB>label
"""
from __future__ import annotations

import datetime
import json
import os
import sys

MANIFEST_PATH = os.environ.get("AFK_MANIFEST", "/tmp/afk_manifest.json")
COUNTER_PATH = os.environ.get("AFK_ROTATION_COUNTER", "/tmp/afk_rotation_counter")
DEFAULT_K = 8


def _read_counter() -> int:
    try:
        with open(COUNTER_PATH) as fh:
            return int(fh.read().strip() or "0")
    except (FileNotFoundError, ValueError):
        return 0


def _write_counter(n: int) -> None:
    with open(COUNTER_PATH, "w") as fh:
        fh.write(str(n))


def main() -> int:
    k = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_K
    with open(MANIFEST_PATH) as fh:
        forms = json.load(fh)["forms"]
    if not forms:
        print("NO_FORMS", file=sys.stderr)
        return 1

    counter = _read_counter()
    doy = datetime.datetime.now(datetime.timezone.utc).timetuple().tm_yday
    n = len(forms)
    k = min(k, n)
    start = ((doy + counter) * k) % n
    chosen = [forms[(start + i) % n] for i in range(k)]

    for f in chosen:
        print(f"{f['kind']}\t{f['url']}\t{f['label']}")

    _write_counter(counter + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
