from django_otp.admin import OTPAdminSite


class SubayAdminSite(OTPAdminSite):
    """The data-entry interface. OTPAdminSite enforces TOTP on every login.

    Defined in its own module (not admin.py) so resolving the lazy default_site
    never re-enters the module that performs @admin.register — which would orphan
    registrations on a throwaway site instance.
    """

    site_header = "SUBAY"
    site_title = "SUBAY"
    index_title = "CMV / Kidney-Transplant Research Database"
