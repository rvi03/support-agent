"""S14 build step 8: run the other safety suites and write eval/reports/suites.md.

`make eval-suites` runs, in order, and records each exit code and its last lines:

- OPA policy tests (`make opa-test`);
- OPA rule-breaks against the live API (`make rule-breaks`);
- itsm-actions rule-breaks, approvals, autonomy, closed ticket and crossed deadline
  (tests/integration/test_itsm.py);
- revision and resume: a reindex during a pause hands off (unit), SLA expiry during
  a pause and the approval/timer race (tests/integration/test_sla_timer.py), an
  expired approval asked again and a stale card refused (test_resolver_walk.py);
- branch safety: the Resolver walk rules (unit test_walk.py, integration
  test_resolver_walk.py; run that one in `make live-mode`: its scripted fixes expect
  the live outcome, and in eval mode the fault cards decide);
- abstention: 20 tune Group A tickets with their runbook family removed must hand
  off `no_kb_match` (`make abstention`);
- the safety checker's own seeded-bad-row tests (unit test_safety_checker.py).

The secret-leak suite runs inside `make safety-check` on every eval run. A revoked
approval has no API in the POC (no revoke concept), so it is listed as not covered.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "eval" / "reports" / "suites.md"
PYTEST = ["uv", "run", "pytest", "-q"]
SUITES: list[tuple[str, list[str]]] = [
    ("OPA policy tests", ["make", "opa-test"]),
    ("OPA rule-breaks (API)", ["make", "rule-breaks"]),
    ("itsm-actions rule-breaks and approvals", [*PYTEST, "tests/integration/test_itsm.py"]),
    ("Revision and resume (unit)", [*PYTEST, "tests/unit/test_revision_resume.py"]),
    ("SLA expiry during a pause, approval/timer race",
     [*PYTEST, "tests/integration/test_sla_timer.py"]),
    ("Branch safety (walk rules, unit)", [*PYTEST, "tests/unit/test_walk.py"]),
    ("Branch safety and resume (live walks)", [*PYTEST, "tests/integration/test_resolver_walk.py"]),
    ("Safety checker seeded bad rows", [*PYTEST, "tests/unit/test_safety_checker.py"]),
    ("Abstention (20 tune tickets, family removed)", ["make", "abstention"]),
]  # fmt: skip


def main(argv: list[str]) -> int:
    only = set(argv)
    lines = ["# Other safety suites (S14 step 8)", "",
             f"Run {datetime.now(UTC):%Y-%m-%d %H:%M}Z.", "",
             "| Suite | Result | Time | Last line |", "|---|---|---|---|"]  # fmt: skip
    fails = 0
    for name, cmd in SUITES:
        if only and not any(o.lower() in name.lower() for o in only):
            continue
        started = time.monotonic()
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S603
        tail = [x for x in (p.stdout + p.stderr).splitlines() if x.strip()][-1:] or ["-"]
        ok = p.returncode == 0
        fails += not ok
        lines.append(
            f"| {name} | {'pass' if ok else '**fail**'} | "
            f"{time.monotonic() - started:.0f} s | {tail[0][:140].replace('|', '/')} |"
        )
        print(f"{name}: {'pass' if ok else 'FAIL'}")
    lines += ["", "- Secret leak (A24): runs inside `make safety-check` on every eval run.",
              "- Revoked approval: not covered; the POC has no revoke action (open item).",
              "- KB-fixture injection (15 cases): needs a test-only KB revision publish on an "
              "idle stack; not run in this pass."]  # fmt: skip
    REPORT.write_text("\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
