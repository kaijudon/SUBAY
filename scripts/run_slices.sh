#!/usr/bin/env bash
#
# run_slices.sh — drive RENOVA slices 03..14 through the Ralph 3-hat pipeline
# (Planner -> Builder -> Reviewer) sequentially, one slice per `ralph run`.
#
# Why a driver: `ralph run` processes ONE prompt file per invocation. Numeric
# order 03->14 is a valid dependency order — every slice card's "Blocked by"
# names only lower-numbered slices, so running them in order satisfies every
# blocker. The loop HALTS on the first slice that fails its gate, because each
# slice builds on the prior one (e.g. 04 needs 03's missed_visit, 10 needs 09's
# Aliquot).
#
# Per slice:
#   1. clear any stale .ralph/loop.lock (a crashed prior loop leaves one and
#      ralph refuses to start),
#   2. ralph run -P SliceNN_prompt.md --max-iterations 10  (tee to a log),
#   3. require LOOP_COMPLETE in that log (Reviewer approval promise),
#   4. independently re-run the real gate: pytest + makemigrations --check +
#      scripts/backpressure.py — belt-and-suspenders against a false approval.
# Any failure -> stop with a non-zero exit and the slice number.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 2
ROOT="$PWD"

ALL_SLICES=(03 04 05 06 07 08 09 10 11 12 13 14)
# Optional first arg = slice to start from (e.g. ./run_slices.sh 04 to resume
# after 03 is already committed). Defaults to the first slice.
START="${1:-${ALL_SLICES[0]}}"
SLICES=()
seen=0
for s in "${ALL_SLICES[@]}"; do
  [[ "$s" == "$START" ]] && seen=1
  [[ "$seen" == 1 ]] && SLICES+=("$s")
done
if [[ ${#SLICES[@]} -eq 0 ]]; then
  echo "FATAL: start slice '$START' not in ${ALL_SLICES[*]}" >&2
  exit 2
fi
MAX_ITERS=10
CONDA="conda run -n renova_env"
LOGDIR="$ROOT/logs"
mkdir -p "$LOGDIR"

run_gate() {
  # Independent verification the Builder's payload can't fake.
  $CONDA python -m pytest -q || return 1
  $CONDA python manage.py makemigrations --check --dry-run || return 1
  $CONDA python scripts/backpressure.py || return 1
}

for n in "${SLICES[@]}"; do
  prompt="$ROOT/Slice${n}_prompt.md"
  log="$LOGDIR/slice-${n}.log"

  if [[ ! -f "$prompt" ]]; then
    echo "FATAL: missing $prompt" >&2
    exit 2
  fi

  echo "==================== Slice ${n} : START $(date -Is) ===================="
  rm -f "$ROOT/.ralph/loop.lock"

  ralph run -H hats.yml -P "$prompt" --max-iterations "$MAX_ITERS" 2>&1 | tee "$log"

  if ! grep -q "LOOP_COMPLETE" "$log"; then
    echo "HALT: Slice ${n} did not reach LOOP_COMPLETE (Reviewer never approved within ${MAX_ITERS} iters). See $log" >&2
    exit 1
  fi

  echo "-------- Slice ${n} : independent gate --------"
  if ! run_gate; then
    echo "HALT: Slice ${n} printed LOOP_COMPLETE but the independent gate FAILED. See $log" >&2
    exit 1
  fi

  echo "==================== Slice ${n} : DONE $(date -Is) ===================="
done

echo "ALL SLICES 03..14 COMPLETE."
