#!/usr/bin/env bash
# Sequential RENOVA slice driver — replaces the old Ralph loop.
# Runs each remaining slice prompt through sandcastle, one at a time, on the
# merged result of the previous slice. Stops on the first failing slice.
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

base="$(git branch --show-current)"

for n in "${SLICES[@]}"; do
  prompt=".sandcastle/prompt-${n}.md"
  branch="agent/slice-${n}"
  if [ ! -f "$prompt" ]; then
    echo "ERROR: $prompt not found" >&2
    exit 1
  fi
  echo "========================================"
  echo "=== RENOVA Slice ${n}  ->  ${prompt}"
  echo "========================================"
  # main.mts puts commits on agent/slice-NN and exits nonzero if the slice ran
  # without emitting the completion signal. The `if` lets us print a clear
  # message before `exit` (set -e would otherwise abort silently). On failure we
  # stop and leave the branch unmerged for review.
  if ! npx tsx .sandcastle/main.mts "$prompt"; then
    echo "ABORT: Slice ${n} did not complete. Commits left on ${branch} (unmerged)." >&2
    echo "Inspect the work, then resume from this slice: $0 ${n} ..." >&2
    exit 1
  fi
  # Slice succeeded — merge its branch into the mainline so the next slice builds
  # on it. A merge conflict trips set -e and aborts, leaving the branch intact.
  echo "Merging ${branch} into ${base}..."
  git merge --no-ff -m "Merge ${branch}" "${branch}"
done

echo "All requested slices complete."
