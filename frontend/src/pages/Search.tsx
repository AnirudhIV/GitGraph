import { useCallback } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, fileHref } from "../api/client";
import { CommitList } from "../components/CommitList";
import { ModuleChip } from "../components/ModuleChip";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";

export function Search() {
  const [params] = useSearchParams();
  const q = params.get("q") ?? "";
  const results = useApi(useCallback(() => (q ? api.search(q) : Promise.resolve(null)), [q]));

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Search results for “{q}”</h1>
      </div>

      {results.loading && <LoadingRows rows={8} />}
      {results.error && <ErrorState error={results.error} onRetry={results.reload} />}

      {results.data && (
        <div className="stack">
          {results.data.files.length === 0 && results.data.authors.length === 0 && results.data.commits.length === 0 && (
            <EmptyState title="No matches" subtitle="Try a shorter or different search term." />
          )}

          {results.data.files.length > 0 && (
            <div className="card card-pad">
              <h2 className="section-title">Files</h2>
              {results.data.files.map((f) => (
                <Link key={f.path} to={fileHref(f.path)} className="link-row">
                  <div className="row-primary">{f.path}</div>
                  <ModuleChip name={f.module} />
                </Link>
              ))}
            </div>
          )}

          {results.data.authors.length > 0 && (
            <div className="card card-pad">
              <h2 className="section-title">Authors</h2>
              {results.data.authors.map((a) => (
                <Link key={a.email} to={`/authors/${encodeURIComponent(a.email)}`} className="link-row">
                  <div>{a.name}</div>
                  <div className="row-secondary">{a.commit_count} commits</div>
                </Link>
              ))}
            </div>
          )}

          {results.data.commits.length > 0 && (
            <div className="card card-pad">
              <h2 className="section-title">Commit messages</h2>
              <CommitList commits={results.data.commits} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
