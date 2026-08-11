#!/usr/bin/env bash
# Point this clone at the versioned hooks in .githooks/.
#
# Run once per clone, including on the deploy box. Hooks under .git/hooks/ are
# not versioned, so a second clone silently has no protection at all - that is
# how agent-attribution trailers reached master in July 2026 despite a hook
# already sitting in .git/hooks/ on the main workstation.
set -euo pipefail

cd "$(dirname "$0")/.."
git config core.hooksPath .githooks
chmod +x .githooks/*

echo "core.hooksPath -> $(git config core.hooksPath)"
echo "active hooks:"
ls -1 .githooks | sed 's/^/  /'
