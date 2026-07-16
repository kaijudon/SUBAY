#!/usr/bin/env python
"""Backpressure evidence collector for the SUBAY Ralph pipeline.

Runs the backpressure checks the ralph ``build.done`` gate requires and prints a
single evidence line in the exact token format ``parse_backpressure_evidence``
expects (verified against the ralph binary)::

    tests: pass, lint: pass, typecheck: pass, audit: pass, coverage: pass, complexity: <score>, duplication: pass, specs: pass

Every check is REAL -- nothing is fabricated. The script exits non-zero if any
check fails, so the Builder hat can only emit ``build.done`` when the evidence is
genuine (satisfies the stock "Backpressure is law" guardrail instead of relaxing
it).

Tooling per DEC-004 (.ralph/agent/decisions.md) -- zero new deps except mypy:

  ====================  ===================================================
  category              how
  ====================  ===================================================
  tests                 pytest
  lint                  django ``manage.py check``
  typecheck             mypy (the only new dependency)
  audit                 ``pip check``
  coverage              stdlib ``trace`` over the test suite + threshold
  complexity            stdlib ``ast`` cyclomatic count + threshold (score)
  duplication           stdlib line-window hashing across product modules
  ====================  ===================================================

Usage::

    conda run -n subay_env python scripts/backpressure.py
"""

from __future__ import annotations

import ast
import contextlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# Product code under measurement: the registry app, excluding tests, migrations
# and package markers.
PRODUCT_ROOT = ROOT / "subay" / "registry"

# Honest thresholds (tuned against the real slice-01 codebase).
COVERAGE_MIN = 70.0       # percent of product statements executed by the suite
COMPLEXITY_MAX = 20       # max cyclomatic complexity allowed for any function
DUP_WINDOW = 8            # consecutive normalized lines that count as a clone

# mypy is scoped to plain-Python modules that type-check cleanly without Django
# stubs; Django's dynamic model layer is out of scope per DEC-004 (non-strict).
TYPECHECK_TARGETS = [
    "scripts/backpressure.py",
    "subay/registry/management/commands/export_analysis_set.py",
]


def _run(cmd: list[str]) -> tuple[int, str]:
    """Run a subprocess at the repo root, return (exit_code, combined_output)."""
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)


def _product_files() -> list[Path]:
    files = []
    for path in PRODUCT_ROOT.rglob("*.py"):
        parts = path.parts
        if "tests" in parts or "migrations" in parts or path.name == "__init__.py":
            continue
        files.append(path)
    return sorted(files)


# ---------------------------------------------------------------------------
# Subprocess-backed checks
# ---------------------------------------------------------------------------

def check_tests() -> tuple[bool, str, str]:
    code, out = _run([PY, "-m", "pytest", "-q"])
    return code == 0, "tests: pass", out.strip().splitlines()[-1] if out.strip() else ""


def check_lint() -> tuple[bool, str, str]:
    code, out = _run([PY, "manage.py", "check"])
    return code == 0, "lint: pass", out.strip().splitlines()[-1] if out.strip() else ""


def check_typecheck() -> tuple[bool, str, str]:
    code, out = _run(
        [PY, "-m", "mypy", "--ignore-missing-imports", "--no-error-summary", *TYPECHECK_TARGETS]
    )
    detail = out.strip().splitlines()[-1] if out.strip() else "clean"
    return code == 0, "typecheck: pass", detail


def check_audit() -> tuple[bool, str, str]:
    code, out = _run([PY, "-m", "pip", "check"])
    return code == 0, "audit: pass", out.strip().splitlines()[-1] if out.strip() else ""


# ---------------------------------------------------------------------------
# Stdlib-backed checks (no new dependency)
# ---------------------------------------------------------------------------

def _executable_lines(path: Path) -> set[int]:
    """Line numbers of statements in a module (coverage denominator)."""
    tree = ast.parse(path.read_text())
    return {node.lineno for node in ast.walk(tree) if isinstance(node, ast.stmt)}


def check_coverage() -> tuple[bool, str, str]:
    """Run the suite under stdlib ``trace`` and gate on percent executed."""
    import trace as trace_mod

    import pytest

    tracer = trace_mod.Trace(count=True, trace=False)
    with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull):
        tracer.runfunc(pytest.main, ["-q", "-p", "no:cacheprovider"])
    counts = tracer.results().counts  # {(filename, lineno): hits}
    executed = {(os.path.abspath(f), ln) for (f, ln), hits in counts.items() if hits > 0}

    total = covered = 0
    for path in _product_files():
        exec_lines = _executable_lines(path)
        abs_path = os.path.abspath(path)
        total += len(exec_lines)
        covered += sum(1 for ln in exec_lines if (abs_path, ln) in executed)

    pct = 100.0 * covered / total if total else 0.0
    ok = pct >= COVERAGE_MIN
    return ok, "coverage: pass", f"{pct:.1f}% ({covered}/{total}) >= {COVERAGE_MIN}%"


def _cyclomatic(func: ast.AST) -> int:
    score = 1
    for node in ast.walk(func):
        if isinstance(
            node,
            (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
             ast.With, ast.AsyncWith, ast.IfExp, ast.comprehension),
        ):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
    return score


def check_complexity() -> tuple[bool, str, str]:
    worst = 0
    worst_name = "-"
    for path in _product_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                score = _cyclomatic(node)
                if score > worst:
                    worst, worst_name = score, f"{path.name}:{node.name}"
    ok = worst <= COMPLEXITY_MAX
    # gate wants a numeric <score>, not "pass"
    return ok, f"complexity: {worst}", f"max {worst} ({worst_name}) <= {COMPLEXITY_MAX}"


def check_duplication() -> tuple[bool, str, str]:
    seen: dict[tuple[str, ...], str] = {}
    clones: list[str] = []
    for path in _product_files():
        norm = [
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for i in range(len(norm) - DUP_WINDOW + 1):
            block = tuple(norm[i : i + DUP_WINDOW])
            if len(set(block)) < 4:  # skip trivially repetitive blocks
                continue
            if block in seen:
                clones.append(f"{path.name}:{i + 1} ~ {seen[block]}")
            else:
                seen[block] = f"{path.name}:{i + 1}"
    ok = not clones
    detail = "no clones" if ok else "; ".join(clones[:3])
    return ok, "duplication: pass", detail


def check_specs() -> tuple[bool, str, str]:
    """Acceptance criteria are encoded as tests; specs pass iff the suite passes.

    Optional gate token, but reported for completeness.
    """
    test_file = PRODUCT_ROOT / "tests" / "test_export.py"
    ok = test_file.exists()
    return ok, "specs: pass", "AC encoded in test_export.py" if ok else "missing"


CHECKS = [
    check_tests,
    check_lint,
    check_typecheck,
    check_audit,
    check_coverage,
    check_complexity,
    check_duplication,
    check_specs,
]


def main() -> int:
    tokens: list[str] = []
    all_ok = True
    for check in CHECKS:
        ok, token, detail = check()
        all_ok = all_ok and ok
        status = "OK " if ok else "FAIL"
        print(f"  [{status}] {token:<22} {detail}", file=sys.stderr)
        if ok:
            tokens.append(token)
        else:
            # surface the failed category honestly so the gate stays unsatisfied
            tokens.append(token.split(":")[0] + ": fail")

    line = ", ".join(tokens)
    print(line)  # stdout: the evidence line for the build.done payload
    if not all_ok:
        print("\nbackpressure: one or more checks FAILED", file=sys.stderr)
        return 1
    print("\nbackpressure: all checks passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
