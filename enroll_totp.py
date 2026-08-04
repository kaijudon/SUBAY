"""Dev helper: enroll a confirmed TOTP device for a user so they can pass the
OTP-enforced admin login. Prints a terminal QR + the otpauth URI + the base32
secret (for manual entry). Not for production - real enrollment is per the
deploy runbook.

    python manage.py shell is not needed; run directly:
        python enroll_totp.py <username>
"""
import sys
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "subay.settings")

import django
django.setup()

import qrcode
from django.contrib.auth import get_user_model
from django_otp.plugins.otp_totp.models import TOTPDevice

if len(sys.argv) != 2:
    sys.exit("usage: python enroll_totp.py <username>")

username = sys.argv[1]
User = get_user_model()
try:
    user = User.objects.get(username=username)
except User.DoesNotExist:
    sys.exit(f"no such user: {username!r} - create the superuser first")

device, created = TOTPDevice.objects.get_or_create(
    user=user, name="default", defaults={"confirmed": True}
)
if not created and not device.confirmed:
    device.confirmed = True
    device.save(update_fields=["confirmed"])

uri = device.config_url
print()
print(f"{'created' if created else 'reusing'} confirmed TOTP device for {username!r}")
print()
qr = qrcode.QRCode(border=1)
qr.add_data(uri)
qr.make()
qr.print_ascii(invert=True)
print()
print("otpauth URI :", uri)
# base32 secret for manual key entry in an authenticator app
import base64
print("manual key  :", base64.b32encode(bytes.fromhex(device.key)).decode())
print()
print("Scan the QR (or enter the manual key) in an authenticator app")
print("(Google Authenticator, Aegis, 1Password, ...), then use the rotating")
print("6-digit code in the admin login's 'OTP token' field.")
