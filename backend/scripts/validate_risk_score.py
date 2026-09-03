"""Standalone, manually-run validation of risk_score against real historical
bugs -- NOT part of the ingest pipeline (seed/load.py, cli/ingest.py) and
never imported by either.

Usage (from the backend/ directory):

    python -m scripts.validate_risk_score --db /path/to/repo/.gitgraph/graph.db --repo-path /path/to/repo

`--db` must point at a graph.db already written by `python -m cli ingest`
(see cli/ingest.py) against the same repo at `--repo-path` -- this script
reuses that ingest's persisted risk_score rather than recomputing it, and
only adds the one thing ingest doesn't persist: bug_fix_count, via
seed.mine_git.mine_function_change_history (see that module for the
bug-fix classification heuristic and its documented caveats).

This is a real test of the risk_score hypothesis, not a marketing exercise:
it reports whatever correlation it finds, weak or strong, and says so
plainly. Spearman (not Pearson) because risk_score = log1p(x) * log1p(y) is
not linear in change_count/caller_count -- Spearman only assumes a
monotonic relationship, which is the actual claim being tested ("higher
risk_score tends to mean more historical bug fixes"), not a specific linear
one.
"""
import argparse
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seed.mine_git import GitOperationError, mine_function_change_history  # noqa: E402

TOP_N_PREVIEW = 15


def _rank(values: list[float]) -> list[float]:
    """Average (fractional) rank per value, ties sharing the mean rank of
    the positions they span -- the standard tie-handling for a Spearman
    correlation; leaving ties unranked (e.g. by insertion order) would
    manufacture a fake ordering among functions that are genuinely tied,
    which is common here since bug_fix_count is a small integer and many
    functions legitimately have exactly 0."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    """Spearman's rho = Pearson correlation computed on ranks rather than
    raw values. Implemented by hand (not scipy.stats.spearmanr) since
    scipy isn't in backend/requirements.txt and this one function is all
    that's needed -- adding a heavy numerical dependency for a single
    correlation coefficient, in a script nothing else imports, isn't worth
    it."""
    n = len(x)
    if n < 2:
        return 0.0
    rx, ry = _rank(x), _rank(y)
    mean_rx, mean_ry = sum(rx) / n, sum(ry) / n
    cov = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    var_x = sum((a - mean_rx) ** 2 for a in rx)
    var_y = sum((b - mean_ry) ** 2 for b in ry)
    if var_x == 0 or var_y == 0:
        # No variance in one of the two series (e.g. every function has the
        # same risk_score, or none has any bug fix at all) -- correlation
        # is undefined, not zero, but 0.0 is the honest "no signal to
        # report" answer for this script's purposes.
        return 0.0
    return cov / math.sqrt(var_x * var_y)


def _describe(rho: float) -> str:
    magnitude = abs(rho)
    if magnitude < 0.1:
        strength = "negligible"
    elif magnitude < 0.3:
        strength = "weak"
    elif magnitude < 0.5:
        strength = "moderate"
    else:
        strength = "strong"
    direction = "positive" if rho >= 0 else "negative"
    return f"{strength} {direction}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="Path to a graph.db written by `python -m cli ingest`")
    parser.add_argument("--repo-path", required=True, help="Local clone matching --db, used to re-mine bug-fix history")
    parser.add_argument("--label", default=None, help="Name to print for this repo (default: --repo-path)")
    args = parser.parse_args()

    label = args.label or args.repo_path

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    functions = [dict(r) for r in conn.execute("SELECT id, path, start_line, end_line, risk_score, change_count FROM functions")]
    conn.close()

    if not functions:
        print(f"[{label}] No functions in {args.db} -- nothing to validate.")
        return

    print(f"[{label}] Re-mining bug-fix history for {len(functions)} functions ...")
    try:
        history = mine_function_change_history(args.repo_path, functions)
    except GitOperationError as exc:
        print(f"[{label}] Could not mine history: {exc}")
        return

    risk_scores = [fn["risk_score"] for fn in functions]
    bug_fix_counts = [history[fn["id"]]["bug_fix_count"] for fn in functions]

    rho = spearman(risk_scores, bug_fix_counts)
    n_with_bug_fix = sum(1 for c in bug_fix_counts if c > 0)
    n_with_risk = sum(1 for s in risk_scores if s > 0)

    print(f"\n[{label}] Spearman correlation (risk_score vs bug_fix_count): rho = {rho:.3f} ({_describe(rho)})")
    print(f"[{label}] n = {len(functions)} functions; {n_with_bug_fix} touched by >=1 bug-fix commit "
          f"(heuristic classifier -- see mine_git.py::_is_bug_fix_commit); {n_with_risk} have risk_score > 0.")

    ranked = sorted(functions, key=lambda fn: fn["risk_score"], reverse=True)[:TOP_N_PREVIEW]
    print(f"\n[{label}] Top {len(ranked)} functions by risk_score (risk_score | change_count | bug_fix_count | id):")
    for fn in ranked:
        bfc = history[fn["id"]]["bug_fix_count"]
        print(f"  {fn['risk_score']:.3f} | {fn['change_count']:>4} | {bfc:>4} | {fn['id']}")

    print(
        f"\n[{label}] Honest read: "
        + (
            "risk_score shows essentially no relationship to which functions actually received bug fixes in this repo's history."
            if abs(rho) < 0.1
            else f"risk_score shows a {_describe(rho)} relationship to bug-fix history in this repo -- "
            "treat this as one data point, not proof, especially given the bug-fix classifier's own "
            "false-positive/false-negative rate (see mine_git.py::_is_bug_fix_commit)."
        )
    )


if __name__ == "__main__":
    main()
