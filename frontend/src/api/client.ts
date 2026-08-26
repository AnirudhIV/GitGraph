import type {
  AuthorDetail,
  AuthorSummary,
  BlastRadius,
  CollabPath,
  FileDetail,
  FileSummary,
  Hotspot,
  ModuleCoupling,
  ModuleSummary,
  RepoStats,
  SearchResult,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  isUnavailable: boolean;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
    this.isUnavailable = status === 503 || status === 0;
  }
}

async function request<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(BASE_URL + path);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== "") url.searchParams.set(key, String(value));
    }
  }

  let res: Response;
  try {
    res = await fetch(url.toString());
  } catch {
    throw new ApiError("Could not reach the API server. Is the backend running?", 0);
  }

  if (!res.ok) {
    let detail = `Request failed with status ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // ignore
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export interface IngestJob {
  job_id: string;
  status: "running" | "done" | "error";
  message: string;
  repo_url: string;
  error: string | null;
  stats: RepoStats | null;
  elapsed_seconds: number | null;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE_URL + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Could not reach the API server. Is the backend running?", 0);
  }

  if (!res.ok) {
    let detail = `Request failed with status ${res.status}`;
    try {
      const json = await res.json();
      if (typeof json?.detail === "string") detail = json.detail;
      else if (Array.isArray(json?.detail) && json.detail[0]?.msg) detail = json.detail[0].msg;
    } catch {
      // ignore
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; database_connected: boolean }>("/api/health"),
  stats: () => request<RepoStats>("/api/stats"),

  startIngest: (repoUrl: string, maxCommits = 5000) =>
    post<{ job_id: string }>("/api/repo/ingest", { repo_url: repoUrl, max_commits: maxCommits }),
  ingestStatus: (jobId: string) => request<IngestJob>(`/api/repo/ingest/${jobId}`),
  hotspots: (limit = 20) => request<Hotspot[]>("/api/hotspots", { limit }),

  files: (search = "", limit = 50) => request<FileSummary[]>("/api/files", { search, limit }),
  file: (path: string) => request<FileDetail>(`/api/files/${encodePath(path)}`),
  blastRadius: (path: string, depth = 2, minCount = 1) =>
    request<BlastRadius>(`/api/files/${encodePath(path)}/blast-radius`, {
      depth,
      min_count: minCount,
    }),

  authors: (search = "", limit = 40) => request<AuthorSummary[]>("/api/authors", { search, limit }),
  author: (email: string) => request<AuthorDetail>(`/api/authors/${encodeURIComponent(email)}`),
  collabPath: (emailA: string, emailB: string) =>
    request<CollabPath>("/api/authors/path", { email_a: emailA, email_b: emailB }),

  modules: () => request<ModuleSummary[]>("/api/modules"),
  moduleCoupling: (limit = 25) => request<ModuleCoupling[]>("/api/modules/coupling", { limit }),

  search: (q: string) => request<SearchResult>("/api/search", { q }),
};

// FastAPI's {path:path} converter expects literal slashes in the URL path
// segment; encodeURIComponent on the whole string would escape them to
// %2F. Encode each segment individually and keep the slashes as separators.
function encodePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

export function fileHref(path: string): string {
  return `/files/${encodePath(path)}`;
}
