# Gunicorn config for SUBAY.
# Binds a Unix socket ONLY — never a TCP port. nginx terminates HTTPS and proxies
# to this socket, so the app is unreachable except via nginx on localhost.
bind = "unix:/run/subay/gunicorn.sock"
# Socket mode 0770 (subay:subay) so nginx can connect ONLY if www-data is added to
# the subay group (see deploy/README.md standup) — not world-accessible.
umask = 0o007
# Control socket for `gunicornc` runtime management. As a systemd system service
# there is no $XDG_RUNTIME_DIR, so gunicorn would default to $HOME/.gunicorn/
# (=/opt/subay/.gunicorn), which ProtectSystem=strict makes read-only. Pin it into
# /run/subay, which is already writable (RuntimeDirectory + ReadWritePaths).
control_socket = "/run/subay/gunicorn.ctl"
workers = 3
timeout = 60
# If this is ever switched to a TCP bind, it must stay 127.0.0.1 — never 0.0.0.0.
