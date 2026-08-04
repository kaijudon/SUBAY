"""SUBAY URLs.

The customized admin remains the only interface for data entry and ops. The two
routes outside it are unauthenticated read-only pages - the landing page and the
protocol summary - which serve no subject-level data (see
`registry/views_public.py`).
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # admin.site is the OTP-enforced SubayAdminSite (see registry/apps.py default_site).
    path("admin/", admin.site.urls),
    # Mounted after the admin so the prefix match is decided by order, not by
    # luck: the public include owns "" and "protocol/" only.
    path("", include("subay.registry.urls_public")),
]
