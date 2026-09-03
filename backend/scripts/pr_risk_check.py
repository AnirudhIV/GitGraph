"""Run by .github/workflows/gitgraph-risk-check.yml on every pull_request.

Finds which functions a PR's diff actually touches -- by intersecting the
diff's changed line ranges with each function's line range, the same
intersection idea mine_git.py::mine_function_change_counts applies to a
single commit's hunks, just applied once to a whole PR diff instead of
once per historical commit -- and flags any that are "high risk": in the
top `--percentile` of the repo's current risk_score distribution, or with
caller_count at or above `--min-callers`.

Writes a PR comment body to `--out` only when at least one function
qualifies. No file written is the expected, common outcome, not an error
-- the workflow only posts a comment when `--out` exists.
"""
import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seed.mine_git import parse_diff_hunks  # noqa: E402


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (the same definition numpy's default
    `interpolation="linear"` uses) -- exact percentile semantics don't
    matter much for a "top N%" cutoff like this one, but interpolating
    rather than rounding to the nearest rank avoids a cutoff that jumps by
    a whole function's risk_score for a repo with relatively few scored
    functions."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100)
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _touched_functions(conn: sqlite3.Connection, changed: dict[str, set[int]]) -> list[sqlite3.Row]:
    touched = []
    for path, lines in changed.items():
        if not lines:
            continue
        for fn in conn.execute("SELECT * FROM functions WHERE path = ?", (path,)).fetchall():
            if any(fn["start_line"] <= ln <= fn["end_line"] for ln in lines):
                touched.append(fn)
    return touched


def _caller_count(conn: sqlite3.Connection, fn_id: str) -> int:
    row = conn.execute("SELECT COUNT(DISTINCT caller_id) AS n FROM calls WHERE callee_id = ?", (fn_id,)).fetchone()
    return row["n"] if row else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="Path to graph.db from `python -m cli ingest` against the PR's tree")
    parser.add_argument("--base", required=True, help="Base ref to diff against, e.g. origin/main")
    parser.add_argument("--percentile", type=float, default=90.0)
    parser.add_argument("--min-callers", type=int, default=5)
    parser.add_argument("--out", required=True, help="Comment body is written here only if something qualifies")
    args = parser.parse_args()

    diff = subprocess.run(
        ["git", "diff", f"{args.base}...HEAD", "--unified=0"],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout
    changed = parse_diff_hunks(diff)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Scored functions only: change_count=0 or caller_count=0 both collapse
    # risk_score to log1p(0)=0 (see seed.parse.compute_risk_score), and in
    # most repos *most* functions land there (never called, or never
    # changed since ingest's mining window). Including those zeros in the
    # percentile would pull a "top 10%" cutoff straight down to 0 -- i.e.
    # "risk_score >= 0", which is every function -- so the percentile is
    # computed only over functions that actually have some signal, the same
    # "null/zero-scored rows don't participate in the ranking" convention
    # app.queries.HOTSPOTS_PRECOMPUTED uses for files.
    scored_risk = [r["risk_score"] for r in conn.execute("SELECT risk_score FROM functions WHERE risk_score > 0").fetchall()]
    threshold = _percentile(scored_risk, args.percentile)

    flagged: list[tuple[sqlite3.Row, int]] = []
    for fn in _touched_functions(conn, changed):
        caller_count = _caller_count(conn, fn["id"])
        if (fn["risk_score"] > 0 and fn["risk_score"] >= threshold) or caller_count >= args.min_callers:
            flagged.append((fn, caller_count))
    conn.close()

    if not flagged:
        return  # nothing crosses the threshold -- the common case, not an error

    flagged.sort(key=lambda pair: pair[0]["risk_score"], reverse=True)
    lines = [
        "### ⚠️ GitGraph: this PR touches high-risk functions",
        "",
        f"Flagged: risk_score in the top {args.percentile:.0f}% for this repo (>= {threshold:.3f}), "
        f"or caller_count >= {args.min_callers}.",
        "",
        "| Function | Callers | Risk score | Change count |",
        "|---|---|---|---|",
    ]
    for fn, caller_count in flagged:
        lines.append(f"| `{fn['qualname']}` ({fn['path']}) | {caller_count} | {fn['risk_score']:.3f} | {fn['change_count']} |")

    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Flagged {len(flagged)} touched high-risk function(s); wrote comment body to {args.out}.")


if __name__ == "__main__":
    main()
