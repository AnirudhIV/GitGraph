import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api, fileHref } from "../api/client";
import { ModuleChip } from "../components/ModuleChip";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";

export function Files() {
  const [search, setSearch] = useState("");
  const files = useApi(useCallback(() => api.files(search, 80), [search]));

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Files</h1>
        <p className="page-subtitle">Every file that has appeared in the last N commits, ranked by commit count.</p>
      </div>

      <div style={{ maxWidth: 420, marginBottom: 20 }}>
        <input
          type="search"
          placeholder="Filter by path…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="card card-pad">
        {files.loading && <LoadingRows rows={10} />}
        {files.error && <ErrorState error={files.error} onRetry={files.reload} />}
        {files.data && files.data.length === 0 && (
          <EmptyState title="No files match" subtitle="Try a different search, or check the seed script ran." />
        )}
        {files.data && files.data.length > 0 && (
          <div>
            {files.data.map((f) => (
              <Link key={f.path} to={fileHref(f.path)} className="link-row">
                <div style={{ minWidth: 0 }}>
                  <div className="row-primary">{f.path}</div>
                  <div style={{ marginTop: 4 }}>
                    <ModuleChip name={f.module} />
                  </div>
                </div>
                <div className="row-secondary">
                  {f.is_deleted && <span style={{ color: "var(--status-critical)", marginRight: 8 }}>deleted</span>}
                  {f.commit_count} commits
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
