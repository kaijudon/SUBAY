#!/usr/bin/env bash
# Start one AFK data-entry usage window (T4 / #15). Fired daily by the systemd
# user timer at the 21:00 UTC usage-limit reset; runs the local-docker pipeline,
# which iterates back-to-back with no cooldown until the Claude usage limit stops
# it. Idempotent to re-run by hand for a manual window.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# Load the harness secrets (CLAUDE_CODE_OAUTH_TOKEN, GH_TOKEN). Gitignored; never
# baked into the unit. Absent .env => the pipeline can't auth, so fail loudly.
if [ -f .sandcastle/.env ]; then
  set -a
  # shellcheck disable=SC1091
  . .sandcastle/.env
  set +a
else
  echo "run-daily-resume: .sandcastle/.env missing (CLAUDE_CODE_OAUTH_TOKEN, GH_TOKEN)" >&2
  exit 1
fi

exec npx --yes tsx .sandcastle/data-entry-tester-pipeline.mts
