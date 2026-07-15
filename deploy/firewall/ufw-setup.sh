#!/usr/bin/env bash
# deploy/firewall/ufw-setup.sh — Slice 15 §2: firewall + SSH lockdown
# =============================================================================
# Run once, as root, on the SPMC box:  sudo deploy/firewall/ufw-setup.sh
#
# Locks the box to a single-operator localhost posture: no inbound anything except
# SSH from the admin subnet, and even that only for maintenance. The app itself is
# NEVER exposed — nginx/gunicorn bind 127.0.0.1 (Slice 0), so no firewall rule is
# needed to reach SUBAY; you use it from the box's own browser.
#
# Acceptance (issue 15): "SSH is key-only (password + root login disabled),
# LAN-bound, with fail2ban and UFW allowing inbound 22 from the admin subnet only."
#
# EDIT ADMIN_SUBNET below to your real LAN range before running. If you never SSH
# in (you sit at the box), set SSH_ENABLED=0 to deny 22 entirely — the safest option.
# =============================================================================
set -euo pipefail

# ---- operator settings ------------------------------------------------------
ADMIN_SUBNET="192.168.1.0/24"   # unused when SSH_ENABLED=0 (this box has no sshd)
SSH_ENABLED=0                   # 0 = no inbound SSH at all (single operator sits at the box)
# -----------------------------------------------------------------------------

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi

echo "==> Resetting UFW to a default-deny posture"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing   # the box needs outbound: apt updates, backup push, alerts

if [[ "$SSH_ENABLED" -eq 1 ]]; then
    echo "==> Allowing inbound SSH (22) from ${ADMIN_SUBNET} only"
    ufw allow from "${ADMIN_SUBNET}" to any port 22 proto tcp
else
    echo "==> SSH disabled — no inbound 22 rule added (deny by default)"
fi

# Deliberately NO rule for 80/443/gunicorn: the app is localhost-only (Slice 0).
echo "==> Enabling UFW"
ufw --force enable
ufw status verbose

cat <<'NEXT'

==> UFW is up. Now harden SSH itself (only if you use SSH):
    sudo cp deploy/firewall/sshd-hardening.conf /etc/ssh/sshd_config.d/10-subay.conf
    # make sure your public key is in ~/.ssh/authorized_keys FIRST, or you lock yourself out
    sudo sshd -t && sudo systemctl restart ssh

==> And fail2ban:
    sudo apt install -y fail2ban
    sudo cp deploy/firewall/fail2ban-jail.local /etc/fail2ban/jail.local
    sudo systemctl enable --now fail2ban
    sudo fail2ban-client status sshd

Verify (issue 15 §2):
    sudo ufw status verbose        # 22 allowed from admin subnet only, all else denied
    sudo sshd -T | grep -E 'passwordauthentication|permitrootlogin'   # both 'no'
NEXT
