"""Static-analysis parsing for the function-level dependency graph
(Function/CALLS/IMPORTS in CognoDB).

This is a wholly separate data source from mine_git.py: it reads actual
file *content* from the working tree at whatever commit is currently
checked out, not git history, and feeds a structurally-derived graph that
never mixes with the git-mined File/Module coupling data (see README).

parse_repo() is the single entrypoint called from seed/load.py::run_ingest,
mirroring how mine_git.mine_commits() is the entrypoint for the git side.
Per-file parse failures are swallowed here (one malformed/generated file
must not lose the rest of the repo's graph); only a total failure of a
whole language's parsing phase (e.g. the Node helper isn't available)
raises ParseOperationError, which seed/load.py treats as a warning, not an
ingest-aborting error.
"""
import math
from collections import defaultdict
from dataclasses import dataclass, field


class ParseOperationError(RuntimeError):
    """Raised when an entire language's parsing phase fails outright.

    Per-file failures inside py_parser/ts_parser are caught and logged at
    that level and never surface as this -- this is reserved for
    whole-phase failures (missing Node runtime, subprocess crash/timeout).
    """


@dataclass
class FunctionDef:
    id: str
    path: str
    name: str
    qualname: str
    language: str
    start_line: int
    end_line: int
    is_exported: bool
    is_method: bool
    source: str = ""
    # McCabe cyclomatic complexity (1 = a single straight-line path, +1 per
    # branch) -- see py_parser.py::_cyclomatic_complexity /
    # ts-analyzer/extract.js's matching walker. Defaults to 1 (not 0): a
    # function with zero branches still has exactly one path through it,
    # and compute_risk_score below relies on complexity never being 0 so
    # this factor never zeroes out an otherwise-real change_count/
    # caller_count signal.
    complexity: int = 1


@dataclass
class CallSite:
    caller_id: str
    callee_id: str
    confidence: str  # "high" | "low"
    resolution: str  # "same_file" | "import_resolved" | "type_checked" | "name_heuristic"
    line: int


@dataclass
class ImportEdge:
    from_path: str
    to_path: str
    imported_names: list[str] = field(default_factory=list)


@dataclass
class ParsedRepo:
    functions: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)
    # Per-language failures that shouldn't abort the whole parse -- e.g. a
    # language whose parser isn't built yet. seed/load.py reports these as
    # warnings rather than raising, same as a whole-phase failure, but
    # without discarding whatever other languages did parse successfully.
    warnings: list[str] = field(default_factory=list)


# Call sites this dense between the same pair are almost always a hot,
# repeatedly-invoked helper -- past this, more line numbers add payload
# size without adding insight over "yes, this pair calls a lot."
MAX_CALL_LINES_PER_PAIR = 20

# A pathological outlier (a generated file, a giant dispatch function) must
# not bloat every Function node's storage/response size just to display
# source on the rare function that's thousands of lines long -- truncated
# rather than dropped, since even a partial view is more useful than none.
MAX_SOURCE_CHARS = 20_000


def _truncate_source(source: str) -> str:
    if len(source) <= MAX_SOURCE_CHARS:
        return source
    return source[:MAX_SOURCE_CHARS] + "\n... (truncated)"


def _dedupe_calls(calls: list[CallSite]) -> list[dict]:
    """Collapse multiple call sites between the same (caller, callee) pair
    into one row -- same "dedupe in Python before the UNWIND write" idiom
    as mine_git.py::distinct_files/rename_pairs. Confidence/resolution use
    whichever is stronger among that pair's call sites (high beats low, so
    one confidently-resolved call site outweighs an unrelated ambiguous
    match to the same target)."""
    grouped: dict[tuple[str, str], dict] = {}
    for c in calls:
        key = (c.caller_id, c.callee_id)
        row = grouped.get(key)
        if row is None:
            grouped[key] = {
                "caller_id": c.caller_id,
                "callee_id": c.callee_id,
                "confidence": c.confidence,
                "resolution": c.resolution,
                "call_count": 1,
                "call_lines": [c.line],
            }
            continue
        row["call_count"] += 1
        if len(row["call_lines"]) < MAX_CALL_LINES_PER_PAIR:
            row["call_lines"].append(c.line)
        if row["confidence"] == "low" and c.confidence == "high":
            row["confidence"] = "high"
            row["resolution"] = c.resolution
    return list(grouped.values())


def _dedupe_imports(imports: list[ImportEdge]) -> list[dict]:
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    for i in imports:
        grouped[(i.from_path, i.to_path)].update(i.imported_names)
    return [
        {"from_path": fp, "to_path": tp, "imported_names": sorted(names)}
        for (fp, tp), names in grouped.items()
    ]


def caller_counts(calls: list[dict]) -> dict[str, int]:
    """Distinct-caller fan-in per function id, from an already-deduped calls
    list (each row already collapsed to one entry per (caller, callee)
    pair -- see _dedupe_calls) -- used to feed the function-level risk score
    without a round trip through CognoDB, since seed/load.py has this data
    in memory already, before any of it is written."""
    counts: dict[str, int] = defaultdict(int)
    for c in calls:
        counts[c["callee_id"]] += 1
    return dict(counts)


def compute_risk_score(change_count: int, caller_count: int, complexity: int = 1) -> float:
    """log1p on change_count/caller_count so neither a single very-hot
    function nor a single very-central one can dominate the score on its
    own -- same reasoning as the file-level risk_score's own
    log(commit_count + 1) term (see app.queries.HOTSPOTS_SIMPLE).
    Multiplicative across all three factors: a function needs to be
    frequently changed *and* widely depended-on *and* structurally complex
    to score high here, matching what "risky" is actually meant to capture
    -- a function that's called constantly but never changes (a stable
    utility), one that changes often but nothing calls (dead-ish code), or
    a complex-but-untouched-and-uncalled function (bad, but not yet a live
    risk) isn't what this is meant to flag on its own.

    complexity is the one factor that's never 0 (see FunctionDef.complexity
    -- a function always has at least one path through it), deliberately:
    change_count=0 or caller_count=0 correctly zero out the whole score
    (no evidence this function is live or connected at all), but a dead-
    simple, heavily-called, frequently-changed function shouldn't be zeroed
    out just for having no branches -- log1p(1) = 0.693 is a real, nonzero
    floor rather than a gate. This is also why complexity uses log1p on the
    raw value (not complexity - 1, the way change_count/caller_count use
    the raw "zero means no evidence" count): the floor is intentional here.

    Shared by seed/load.py (CognoDB ingest) and cli/ingest.py (local
    SQLite ingest) so the two pipelines can never compute this differently.
    """
    return round(math.log1p(change_count) * math.log1p(caller_count) * math.log1p(complexity), 4)


def parse_repo(repo_path: str, file_list: list[str]) -> ParsedRepo:
    """Parse every file in file_list (already the deduplicated, mined file
    list from seed/mine_git.py::distinct_files) whose extension this module
    knows how to handle, dispatching per-language, then dedupes calls/
    imports before returning.

    Any file extension with no parser registered is silently skipped --
    "no function-level data for this file" is a strictly smaller feature
    surface than a broken ingest, same philosophy as the whole-phase
    failure handling in seed/load.py::run_ingest.
    """
    py_files = [p for p in file_list if p.endswith(".py")]
    ts_files = [p for p in file_list if p.endswith((".ts", ".tsx", ".js", ".jsx"))]

    functions: list[FunctionDef] = []
    calls: list[CallSite] = []
    imports: list[ImportEdge] = []
    warnings: list[str] = []

    # Each language is isolated in its own try/except: one language's
    # parser being unavailable/broken (e.g. TS/JS before Phase 2 lands)
    # must not discard another language's successfully-parsed data.
    if py_files:
        from seed.parse import py_parser

        try:
            py_functions, py_calls, py_imports = py_parser.parse(repo_path, py_files)
            functions += py_functions
            calls += py_calls
            imports += py_imports
        except ParseOperationError as exc:
            warnings.append(f"Python parsing failed: {exc}")

    if ts_files:
        from seed.parse import ts_parser

        try:
            ts_functions, ts_calls, ts_imports = ts_parser.parse(repo_path, ts_files)
            functions += ts_functions
            calls += ts_calls
            imports += ts_imports
        except ParseOperationError as exc:
            warnings.append(f"TypeScript/JavaScript parsing failed: {exc}")

    return ParsedRepo(
        warnings=warnings,
        functions=[
            {
                "id": f.id,
                "path": f.path,
                "name": f.name,
                "qualname": f.qualname,
                "language": f.language,
                "start_line": f.start_line,
                "end_line": f.end_line,
                "is_exported": f.is_exported,
                "is_method": f.is_method,
                "source": _truncate_source(f.source),
                "complexity": f.complexity,
            }
            for f in functions
        ],
        calls=_dedupe_calls(calls),
        imports=_dedupe_imports(imports),
    )
