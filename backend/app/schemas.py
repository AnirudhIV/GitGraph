"""Pydantic response models returned by the API.

Domain: a repository intelligence graph mined from real `git log` history.
Nodes: Author, Commit, File, Module. See README for the full data model.
"""
from pydantic import BaseModel


class RepoStatsOut(BaseModel):
    file_count: int
    commit_count: int
    author_count: int
    module_count: int
    first_commit_at: str | None
    last_commit_at: str | None


class HotspotOut(BaseModel):
    path: str
    module: str
    commit_count: int
    coupled_file_count: int
    author_count: int
    coupling_density: float
    risk_score: float
    risk_score_recent: float


class FileSummaryOut(BaseModel):
    path: str
    extension: str
    module: str
    commit_count: int
    is_deleted: bool
    risk_score: float | None


class RecentCommitOut(BaseModel):
    hash: str
    message: str
    author_name: str
    timestamp: str
    additions: int
    deletions: int


class OwnerOut(BaseModel):
    author_name: str
    author_email: str
    commit_count: int
    share: float


class CoChangeOut(BaseModel):
    path: str
    module: str
    shared_commits: int


class FileDetailOut(BaseModel):
    path: str
    extension: str
    module: str
    is_deleted: bool
    renamed_to: str | None
    commit_count: int
    first_commit_at: str | None
    last_commit_at: str | None
    risk_score: float | None
    risk_score_recent: float | None
    recent_commits: list[RecentCommitOut]
    owners: list[OwnerOut]
    co_changes: list[CoChangeOut]


class GraphNode(BaseModel):
    id: str
    kind: str  # File | Module
    label: str
    subtitle: str = ""
    hop: int = 0
    weight: float = 1.0
    # Repo-map-specific flags (default false elsewhere): sole_owned means
    # every commit that ever touched this file came from one author (a
    # categorically different danger than a low author_count smoothed into
    # risk_score); trending_worse means risk_score_recent > risk_score, i.e.
    # this file's risk is climbing, not just historically high.
    sole_owned: bool = False
    trending_worse: bool = False
    # Generic category-to-color-by, e.g. an author's primary module in team
    # topology -- reused via moduleColorVar() on the frontend rather than a
    # new color scheme. Empty string (falsy) where a node has no such group.
    group: str = ""


class GraphEdge(BaseModel):
    source: str
    target: str
    weight: float
    # Only meaningful for structurally-derived edges (function call graph --
    # see FunctionSummaryOut et al.); every git-mined edge (coupling,
    # collaboration, ...) has no notion of confidence and keeps the default.
    confidence: str = "high"


class BlastRadiusOut(BaseModel):
    root: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool


class AuthorSummaryOut(BaseModel):
    email: str
    name: str
    commit_count: int
    file_count: int
    first_commit_at: str | None
    last_commit_at: str | None


class AuthorFileOut(BaseModel):
    path: str
    module: str
    commit_count: int


class AuthorDetailOut(AuthorSummaryOut):
    top_files: list[AuthorFileOut]
    top_modules: list[dict]


class AuthorCriticalityOut(BaseModel):
    email: str
    name: str
    criticality_score: float
    sole_owned_file_count: int
    # Computed at request time from last_commit_at, not stored -- see the
    # comment above Settings.author_stale_after_days in config.py.
    is_stale: bool


class SuccessionFileOut(BaseModel):
    path: str
    module: str
    commit_count: int
    last_touched: str | None


class AuthorNetworkOut(BaseModel):
    root: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    at_risk_files: list[SuccessionFileOut]


class AuthorTopologyOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class CollabPathStepOut(BaseModel):
    kind: str  # Author | File
    id: str
    label: str


class CollabPathOut(BaseModel):
    found: bool
    hops: int
    steps: list[CollabPathStepOut]


class ModuleSummaryOut(BaseModel):
    name: str
    file_count: int
    commit_count: int
    author_count: int


class ModuleCouplingOut(BaseModel):
    module_a: str
    module_b: str
    shared_commits: int


class ModuleGraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class RepoMapOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class SearchResultOut(BaseModel):
    files: list[FileSummaryOut]
    authors: list[AuthorSummaryOut]
    commits: list[RecentCommitOut]


# ---------------------------------------------------------------------------
# Function-level call graph -- structurally derived from static source
# parsing (backend/seed/parse/), not from git history. A distinct graph from
# everything above: Function/CALLS/IMPORTS never appear in a File/Module/
# Author/Commit response, and vice versa. See README for why.
# ---------------------------------------------------------------------------


class FunctionSummaryOut(BaseModel):
    id: str
    name: str
    qualname: str
    path: str
    language: str
    start_line: int
    end_line: int
    is_exported: bool
    is_method: bool


class FunctionCallOut(BaseModel):
    id: str
    name: str
    path: str
    confidence: str
    call_count: int


class FunctionDetailOut(FunctionSummaryOut):
    source: str
    callers: list[FunctionCallOut]
    callees: list[FunctionCallOut]


class CallGraphOut(BaseModel):
    root: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool


class FileCallGraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class FunctionListItemOut(FunctionSummaryOut):
    caller_count: int
    callee_count: int
    # change_count: distinct commits whose diff touched a line inside this
    # function's current range (seed/mine_git.py::mine_function_change_counts) --
    # real per-function churn, not the file's own commit_count. risk_score:
    # log1p(change_count) * log1p(caller_count) -- see seed/load.py for why
    # multiplicative (needs to be both frequently changed *and* widely
    # depended-on to score high, not either alone).
    change_count: int
    risk_score: float


class FunctionMapOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
