"""RENOVA URLs. The customized admin is the only interface (data entry + ops)."""
from django.contrib import admin
from django.urls import path

urlpatterns = [
    # admin.site is the OTP-enforced RenovaAdminSite (see registry/apps.py default_site).
    path("admin/", admin.site.urls),
]
