#!/usr/bin/env bash
# Sequential SUBAY slice driver — replaces the old Ralph loop.
# Runs each remaining slice through the multi-agent pipeline
# (.sandcastle/main-pipeline.mts: Planner -> Builder <-> Reviewer), one at a time.
# The pipeline commits on agent/slice-NN and, on approval, merges into the
# mainline itself — so this loop does NOT merge. It just stops on the first
# slice that fails (nonzero exit).
#
# Usage:
#   .sandcastle/run-slices.sh            # run the default slice list
#   .sandcastle/run-slices.sh 11 12      # run only these slices, in order
set -euo pipefail

# Run from the project root regardless of where the script is invoked.
cd "$(dirname "$0")/.."

# Default slice list (edit or pass args to resume from a later slice).
if [ "$#" -gt 0 ]; then
  SLICES=("$@")
else
  SLICES=(09 10 11 12 13 14)
fi

for n in "${SLICES[@]}"; do
  echo "========================================"
  echo "=== SUBAY Slice ${n} (Planner -> Builder <-> Reviewer)"
  echo "========================================"
  # main-pipeline.mts exits nonzero if any stage blocks or no approval is reached.
  # The `if` lets us print a clear message before `exit` (set -e would otherwise
  # abort silently). On success the pipeline already merged agent/slice-${n}.
  if ! npx tsx .sandcastle/main-pipeline.mts "$n"; then
    echo "ABORT: Slice ${n} did not complete. Commits left on agent/slice-${n} (unmerged)." >&2
    echo "Inspect the work, then resume from this slice: $0 ${n} ..." >&2
    exit 1
  fi
done

echo "All requested slices complete."
