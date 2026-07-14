#!/usr/bin/env python
"""Print the current TOTP token for a device, and optionally clear its throttle.

Usage (env must be loaded via `renova-env` and renova_env conda env active):
    python scripts/otp_token.py                 # token for the 'operator' device
    python scripts/otp_token.py --reset         # clear throttle lockout, then token
    python scripts/otp_token.py --device admin  # a different device name
"""
import argparse
import os
import sys
from pathlib import Path

import django

# Make the project root importable no matter where this is run from, so
# `renova.settings` resolves even though this file lives in scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "renova.settings")
django.setup()

from django_otp.oath import totp  # noqa: E402  (must follow django.setup())
from django_otp.plugins.otp_totp.models import TOTPDevice  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="operator", help="TOTPDevice.name (default: operator)")
    parser.add_argument("--reset", action="store_true", help="clear the throttle lockout first")
    args = parser.parse_args()

    try:
        device = TOTPDevice.objects.get(name=args.device)
    except TOTPDevice.DoesNotExist:
        names = list(TOTPDevice.objects.values_list("name", flat=True))
        parser.error(f"no TOTPDevice named {args.device!r}. Existing devices: {names or 'none'}")

    if args.reset:
        device.throttle_reset()
        print(f"throttle reset (failures now: {device.throttling_failure_count})")

    token = str(totp(device.bin_key, device.step, device.t0, device.digits, device.drift))
    print(f"current token: {token.zfill(device.digits)}")
    print(f"(valid ~{device.step}s; user={device.user}, confirmed={device.confirmed})")


if __name__ == "__main__":
    main()
