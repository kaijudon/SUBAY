"""URLs for the two unauthenticated pages. Namespaced `public:` so a template
can never accidentally reverse an admin view through them, and vice versa."""
from django.urls import path

from . import views_public

app_name = "public"

urlpatterns = [
    path("", views_public.landing, name="landing"),
    path("protocol/", views_public.protocol, name="protocol"),
]
