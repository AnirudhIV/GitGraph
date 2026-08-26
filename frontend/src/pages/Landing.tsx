import { useEffect, useRef, useState } from "react";
import { api, ApiError, type IngestJob } from "../api/client";

const EXAMPLES = ["https://github.com/pallets/flask", "https://github.com/expressjs/express"];

export function Landing({ onTracked }: { onTracked: () => void }) {
  const [repoUrl, setRepoUrl] = useState("");
  const [job, setJob] = useState<IngestJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [now, setNow] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAtRef = useRef(0);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  useEffect(() => {
    if (job?.status !== "running") return;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [job?.status]);

  function pollJob(jobId: string) {
    pollRef.current = setInterval(async () => {
      try {
        const latest = await api.ingestStatus(jobId);
        setJob(latest);
        if (latest.status !== "running" && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          if (latest.status === "done") onTracked();
          if (latest.status === "error") setError(latest.error ?? "Ingest failed.");
        }
      } catch (err) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        setError(err instanceof ApiError ? err.message : "Lost contact with the server while tracking progress.");
      }
    }, 1500);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const url = repoUrl.trim();
    if (!url || submitting) return;
    setSubmitting(true);
    setError(null);
    setJob(null);
    try {
      const { job_id } = await api.startIngest(url);
      startedAtRef.current = Date.now();
      setNow(Date.now());
      setJob({
        job_id,
        status: "running",
        message: "Starting…",
        repo_url: url,
        error: null,
        stats: null,
        elapsed_seconds: null,
      });
      pollJob(job_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the import.");
    } finally {
      setSubmitting(false);
    }
  }

  const running = job?.status === "running";

  return (
    <div style={{ maxWidth: 640, margin: "8vh auto 0" }}>
      <div style={{ textAlign: "center", marginBottom: 32 }}>
        <h1 className="page-title" style={{ fontSize: 28, marginBottom: 10 }}>
          Turn a repository's history into a graph
        </h1>
        <p className="page-subtitle" style={{ margin: "0 auto", maxWidth: "48ch" }}>
          Paste the link to any public git repository. We'll clone it, mine every commit with{" "}
          <code>git log --numstat</code>, and load authors, files and modules into a graph you can explore. We only
          fetch the commits we're about to mine, so this stays fast even on repos with huge histories.
        </p>
      </div>

      <form onSubmit={onSubmit} className="card card-pad" style={{ display: "flex", gap: 10 }}>
        <input
          type="text"
          placeholder="https://github.com/owner/repo"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          disabled={running}
          autoFocus
        />
        <button type="submit" className="btn btn-primary" disabled={running || !repoUrl.trim()}>
          {running ? "Tracking…" : "Track repository"}
        </button>
      </form>

      <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--text-muted)", textAlign: "center" }}>
        Try{" "}
        {EXAMPLES.map((url, i) => (
          <span key={url}>
            {i > 0 && " · "}
            <button
              type="button"
              onClick={() => setRepoUrl(url)}
              disabled={running}
              style={{
                background: "none",
                border: "none",
                padding: 0,
                color: "var(--cat-1)",
                cursor: running ? "default" : "pointer",
                font: "inherit",
              }}
            >
              {url.replace("https://github.com/", "")}
            </button>
          </span>
        ))}
      </div>

      {job && (
        <div className="card card-pad" style={{ marginTop: 20 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {running && <span className="skeleton" style={{ width: 14, height: 14, borderRadius: "50%" }} />}
              <span style={{ fontSize: 13.5, fontWeight: 600 }}>
                {job.status === "done" ? "Done — loading your graph…" : job.message}
              </span>
            </div>
            <span
              className="mono"
              style={{ fontSize: 12, color: "var(--text-muted)", fontVariantNumeric: "tabular-nums" }}
            >
              {running && startedAtRef.current > 0
                ? `${Math.max(0, Math.floor((now - startedAtRef.current) / 1000))}s elapsed`
                : job.elapsed_seconds != null
                  ? `${job.elapsed_seconds}s total`
                  : null}
            </span>
          </div>
          {job.status === "done" && job.stats && (
            <div style={{ marginTop: 8, fontSize: 12.5, color: "var(--text-secondary)" }}>
              {job.stats.file_count.toLocaleString()} files · {job.stats.commit_count.toLocaleString()} commits ·{" "}
              {job.stats.author_count.toLocaleString()} authors
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="error-state" style={{ marginTop: 20 }}>
          <div className="error-state-title">Couldn't track that repository</div>
          <div>{error}</div>
        </div>
      )}
    </div>
  );
}
