# Gunicorn config for RENOVA.
# Binds a Unix socket ONLY — never a TCP port. nginx terminates HTTPS and proxies
# to this socket, so the app is unreachable except via nginx on localhost.
bind = "unix:/run/renova/gunicorn.sock"
# Socket mode 0770 (renova:renova) so nginx can connect ONLY if www-data is added to
# the renova group (see deploy/README.md standup) — not world-accessible.
umask = 0o007
workers = 3
timeout = 60
# If this is ever switched to a TCP bind, it must stay 127.0.0.1 — never 0.0.0.0.
