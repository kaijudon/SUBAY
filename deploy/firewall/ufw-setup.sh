#!/usr/bin/env bash
# SUBAY — UFW firewall setup (Slice 15, AC2).
# Run once on the real box as root (HITL checkpoint). Idempotent.
#
# WHY: default-deny inbound. The app is localhost-only (nginx on 127.0.0.1), so the
# ONLY inbound port the LAN needs is SSH (22), and only from the admin subnet.
set -euo pipefail

# --- EDIT THIS to the real admin subnet before running. ---
ADMIN_SUBNET="192.0.2.0/24"

ufw --force reset
ufw default deny incoming
ufw default allow outgoing

# SSH from the admin subnet only. No 80/443 rule: nginx binds 127.0.0.1, never the LAN.
ufw allow from "${ADMIN_SUBNET}" to any port 22 proto tcp comment 'admin SSH only'

ufw --force enable
ufw status verbose
