"""enroll_totp — bootstrap a TOTP device for a user so admin OTP login works.

The admin login page's "OTP Device" dropdown is empty until the account has a
*confirmed* TOTPDevice. This command creates (or reuses) one and prints the
enrollment secret so it can be added to an authenticator app (Google
Authenticator, Aegis, 1Password, …). It replaces the one-off generate_OTP.py.

Usage (env loaded, renova_env active):
    python manage.py enroll_totp cmvprojectuser              # device 'operator'
    python manage.py enroll_totp cmvprojectuser --device admin
    python manage.py enroll_totp cmvprojectuser --qr         # print scannable QR
    python manage.py enroll_totp cmvprojectuser --token      # also print a token now
    python manage.py enroll_totp cmvprojectuser --rotate     # new secret for an
                                                             # existing device

The device is created already-confirmed: this is an operator-run bootstrap on a
trusted box, matching the single-operator deploy model. Treat the printed secret
like a password — anyone who has it can generate valid tokens.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = "Enroll (or reset) a confirmed TOTP device for a user and print its enrollment secret."

    def add_arguments(self, parser):
        parser.add_argument("username", help="username of the account to enroll")
        parser.add_argument(
            "--device", default="operator", help="TOTPDevice.name (default: operator)"
        )
        parser.add_argument(
            "--qr", action="store_true", help="print a scannable ASCII QR of the config URL"
        )
        parser.add_argument(
            "--token", action="store_true", help="also print the current valid token"
        )
        parser.add_argument(
            "--rotate",
            action="store_true",
            help="generate a fresh secret for an existing device (invalidates old enrollments)",
        )

    def handle(self, *args, username, device, qr, token, rotate, **options):
        User = get_user_model()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            names = list(User.objects.values_list("username", flat=True))
            raise CommandError(f"no user named {username!r}. Existing users: {names or 'none'}")

        dev, created = TOTPDevice.objects.get_or_create(user=user, name=device)
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created TOTP device {device!r} for {username}."))
        else:
            if not rotate:
                raise CommandError(
                    f"user {username!r} already has a TOTP device {device!r}. Its existing "
                    f"secret is not printed. Re-run with --rotate to issue a NEW secret "
                    f"(this invalidates any authenticator app already set up), or use "
                    f"`scripts/otp_token.py --device {device}` to read the current token."
                )
            dev.key = TOTPDevice._meta.get_field("key").default()
            self.stdout.write(self.style.WARNING(f"Rotated secret for TOTP device {device!r}."))

        # Confirm so the device shows up in the admin login dropdown.
        dev.confirmed = True
        dev.save()

        self.stdout.write("")
        self.stdout.write(f"user:       {username}")
        self.stdout.write(f"device:     {dev.name} (confirmed={dev.confirmed})")
        self.stdout.write(f"secret:     {dev.bin_key.hex()}")
        self.stdout.write(f"config_url: {dev.config_url}")

        if qr:
            try:
                import qrcode

                q = qrcode.QRCode()
                q.add_data(dev.config_url)
                q.print_ascii(invert=True)
            except ImportError:
                self.stdout.write(
                    self.style.WARNING("(qrcode not installed — enter the secret manually)")
                )

        if token:
            code = str(totp(dev.bin_key, dev.step, dev.t0, dev.digits, dev.drift))
            self.stdout.write("")
            self.stdout.write(f"current token: {code.zfill(dev.digits)} (valid ~{dev.step}s)")

        self.stdout.write("")
        self.stdout.write(
            self.style.NOTICE(
                "Add the secret/config_url to an authenticator app, then log in at "
                "/admin/ selecting this device."
            )
        )
