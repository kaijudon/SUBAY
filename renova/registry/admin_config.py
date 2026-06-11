from django.contrib.admin.apps import AdminConfig


class RenovaAdminConfig(AdminConfig):
    """Replaces django.contrib.admin with the OTP-enforced RENOVA admin site.

    Lives in its own module (not apps.py) and is referenced by explicit class
    path in INSTALLED_APPS, so it never collides with RegistryConfig during
    Django's default-AppConfig detection.
    """

    default_site = "renova.registry.sites.RenovaAdminSite"
