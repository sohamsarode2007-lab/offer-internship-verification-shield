"""How fragile are the hand-set weights? Perturb each W_* constant and count how many evaluation verdicts change band.

    python -m scripts.weight_sensitivity [--pct 25]

Uses the author-written evaluation set, so it measures stability of the rules, not accuracy. It needs no network.
A weight whose +/- change flips many verdicts is one the evidence has not pinned down; a weight that flips none
could be anything in that range without effect on this set.
"""
import argparse
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "eval"))
import run_eval  # noqa: E402

from app.services import risk_scoring  # noqa: E402

WEIGHTS = [n for n in dir(risk_scoring) if n.startswith("W_") and isinstance(getattr(risk_scoring, n), float)]


def bands():
    with contextlib.redirect_stdout(io.StringIO()):
        results = run_eval.evaluate(run_eval.load_cases())
    return {r["case_id"]: r["predicted_band"] for r in results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pct", type=float, default=25.0)
    args = parser.parse_args()
    base = bands()
    print(f"{len(base)} cases; each weight changed by -{args.pct:g}% and +{args.pct:g}% (others fixed)\n")
    print(f"{'weight':26}{'value':>7}{'flips -':>9}{'flips +':>9}   cases that change")
    for name in WEIGHTS:
        original = getattr(risk_scoring, name)
        changed = {}
        for sign in (-1, 1):
            setattr(risk_scoring, name, original * (1 + sign * args.pct / 100))
            now = bands()
            changed[sign] = sorted(c for c in base if now[c] != base[c])
        setattr(risk_scoring, name, original)
        print(f"{name:26}{original:7g}{len(changed[-1]):9}{len(changed[1]):9}   {' '.join(sorted(set(changed[-1]) | set(changed[1])))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
