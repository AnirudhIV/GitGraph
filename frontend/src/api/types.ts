export interface RepoStats {
  file_count: number;
  commit_count: number;
  author_count: number;
  module_count: number;
  first_commit_at: string | null;
  last_commit_at: string | null;
}

export interface Hotspot {
  path: string;
  module: string;
  commit_count: number;
  coupled_file_count: number;
  author_count: number;
  coupling_density: number;
  risk_score: number;
  risk_score_recent: number;
}

export interface FileSummary {
  path: string;
  extension: string;
  module: string;
  commit_count: number;
  is_deleted: boolean;
  risk_score: number | null;
}

export interface RecentCommit {
  hash: string;
  message: string;
  author_name: string;
  timestamp: string;
  additions: number;
  deletions: number;
}

export interface Owner {
  author_name: string;
  author_email: string;
  commit_count: number;
  share: number;
}

export interface CoChange {
  path: string;
  module: string;
  shared_commits: number;
}

export interface FileDetail {
  path: string;
  extension: string;
  module: string;
  is_deleted: boolean;
  renamed_to: string | null;
  commit_count: number;
  first_commit_at: string | null;
  last_commit_at: string | null;
  risk_score: number | null;
  risk_score_recent: number | null;
  recent_commits: RecentCommit[];
  owners: Owner[];
  co_changes: CoChange[];
}

export interface GraphNode {
  id: string;
  kind: string;
  label: string;
  subtitle: string;
  hop: number;
  weight: number;
  sole_owned: boolean;
  trending_worse: boolean;
  group: string;
}

export interface AuthorTopology {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphEdge {
  source: string;
  target: string;
  weight: number;
  // Always present on real API responses (backend defaults it to "high");
  // optional here only so hand-authored edges (e.g. Home.tsx's static demo
  // graph) don't need to set a field that's meaningless for them.
  confidence?: string;
}

export interface BlastRadius {
  root: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
}

export interface AuthorSummary {
  email: string;
  name: string;
  commit_count: number;
  file_count: number;
  first_commit_at: string | null;
  last_commit_at: string | null;
}

export interface AuthorCriticality {
  email: string;
  name: string;
  criticality_score: number;
  sole_owned_file_count: number;
  is_stale: boolean;
}

export interface AuthorFile {
  path: string;
  module: string;
  commit_count: number;
}

export interface AuthorDetail extends AuthorSummary {
  top_files: AuthorFile[];
  top_modules: { name: string; touches: number }[];
}

export interface SuccessionFile {
  path: string;
  module: string;
  commit_count: number;
  last_touched: string | null;
}

export interface AuthorNetwork {
  root: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  at_risk_files: SuccessionFile[];
}

export interface CollabPathStep {
  kind: string;
  id: string;
  label: string;
}

export interface CollabPath {
  found: boolean;
  hops: number;
  steps: CollabPathStep[];
}

export interface ModuleSummary {
  name: string;
  file_count: number;
  commit_count: number;
  author_count: number;
}

export interface ModuleCoupling {
  module_a: string;
  module_b: string;
  shared_commits: number;
}

export interface ModuleGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface RepoMap {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface SearchResult {
  files: FileSummary[];
  authors: AuthorSummary[];
  commits: RecentCommit[];
}

// Function-level call graph -- structurally derived from static source
// parsing (backend/seed/parse/), not from git history. A separate graph
// from everything above: Function/CALLS/IMPORTS never appear in a
// File/Module/Author/Commit response, and vice versa.

export interface FunctionSummary {
  id: string;
  name: string;
  qualname: string;
  path: string;
  language: string;
  start_line: number;
  end_line: number;
  is_exported: boolean;
  is_method: boolean;
}

export interface FunctionCall {
  id: string;
  name: string;
  path: string;
  confidence: string;
  call_count: number;
}

export interface FunctionDetail extends FunctionSummary {
  source: string;
  callers: FunctionCall[];
  callees: FunctionCall[];
}

export interface CallGraph {
  root: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
}

export interface FileCallGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface FunctionListItem extends FunctionSummary {
  caller_count: number;
  callee_count: number;
  // change_count: distinct commits whose diff touched a line inside this
  // function's current range -- real per-function churn, not the file's.
  // risk_score: log1p(change_count) * log1p(caller_count).
  change_count: number;
  risk_score: number;
}

export interface FunctionMap {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
