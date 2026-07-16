# Gunicorn config for SUBAY.
# Binds a Unix socket ONLY — never a TCP port. nginx terminates HTTPS and proxies
# to this socket, so the app is unreachable except via nginx on localhost.
bind = "unix:/run/subay/gunicorn.sock"
workers = 3
timeout = 60
# If this is ever switched to a TCP bind, it must stay 127.0.0.1 — never 0.0.0.0.
