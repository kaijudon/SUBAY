"""Django settings for SUBAY — Slice 0 walking skeleton.

RENal transplant Observational Viral Archive. Self-hosted, localhost-only,
single system-of-record for the CMV / kidney-transplant study.
"""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["127.0.0.1", "localhost"]),
)
# Secrets load from a systemd-supplied env file in production; .env is dev-only.
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-key-do-not-use-in-production")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    # OTP-enforced admin site replaces django.contrib.admin (TOTP on every login).
    "subay.registry.admin_config.SubayAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "simple_history",
    "subay.registry",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # OTPMiddleware must sit after AuthenticationMiddleware.
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Attributes each change to the request user for django-simple-history.
    "simple_history.middleware.HistoryRequestMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "subay.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Project templates win over app templates (filesystem loader runs first),
        # so admin/base_site.html here overrides the contrib.admin default.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "subay.wsgi.application"

# sqlite keeps tests zero-setup; production sets DATABASE_URL to Postgres via the systemd env file.
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# Admin reskin stylesheet lives here (zero-dependency theme via CSS custom props).
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Genotyping ingest stores content-addressed files (named by SHA-256) here. The
# "encrypted volume" requirement is an at-rest/ops concern (DEC-020): the code
# targets MEDIA_ROOT and the deployment mounts it on an encrypted volume — no
# crypto Python dependency is added (no-new-dep rule, DEC-002 lineage).
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))
