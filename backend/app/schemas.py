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


class GraphEdge(BaseModel):
    source: str
    target: str
    weight: float


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
