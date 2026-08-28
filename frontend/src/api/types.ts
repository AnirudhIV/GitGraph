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
}

export interface GraphEdge {
  source: string;
  target: string;
  weight: number;
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
