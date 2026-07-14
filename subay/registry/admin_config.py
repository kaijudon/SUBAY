from django.contrib.admin.apps import AdminConfig


class SubayAdminConfig(AdminConfig):
    """Replaces django.contrib.admin with the OTP-enforced SUBAY admin site.

    Lives in its own module (not apps.py) and is referenced by explicit class
    path in INSTALLED_APPS, so it never collides with RegistryConfig during
    Django's default-AppConfig detection.
    """

    default_site = "subay.registry.sites.SubayAdminSite"
