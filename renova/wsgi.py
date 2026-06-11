"""WSGI entrypoint for RENOVA (served by gunicorn over a Unix socket)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "renova.settings")

application = get_wsgi_application()
