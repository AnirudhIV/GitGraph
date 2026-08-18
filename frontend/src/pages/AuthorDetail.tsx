import { useCallback } from "react";
import { useParams } from "react-router-dom";
import { api, fileHref } from "../api/client";
import { BarList } from "../components/BarList";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { StatTile } from "../components/StatTile";
import { useApi } from "../hooks/useApi";

export function AuthorDetail() {
  const { email = "" } = useParams();
  const author = useApi(useCallback(() => api.author(email), [email]));

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">{author.data?.name ?? "Author"}</h1>
        <p className="page-subtitle mono" style={{ fontSize: 12.5 }}>
          {email}
        </p>
      </div>

      {author.loading && <LoadingRows rows={4} height={60} />}
      {author.error && <ErrorState error={author.error} onRetry={author.reload} />}

      {author.data && (
        <div className="stack">
          <div className="grid grid-stats">
            <StatTile label="Commits" value={author.data.commit_count} />
            <StatTile label="Files touched" value={author.data.file_count} />
            <StatTile
              label="First commit"
              value={author.data.first_commit_at ? new Date(author.data.first_commit_at).toLocaleDateString() : "—"}
            />
            <StatTile
              label="Last commit"
              value={author.data.last_commit_at ? new Date(author.data.last_commit_at).toLocaleDateString() : "—"}
            />
          </div>

          <div className="grid grid-2">
            <div className="card card-pad">
              <h2 className="section-title">Most-touched files</h2>
              {author.data.top_files.length === 0 ? (
                <EmptyState title="No files found" />
              ) : (
                <BarList
                  items={author.data.top_files.map((f) => ({
                    key: f.path,
                    label: f.path,
                    sublabel: f.module,
                    value: f.commit_count,
                    href: fileHref(f.path),
                  }))}
                />
              )}
            </div>

            <div className="card card-pad">
              <h2 className="section-title">Modules worked in</h2>
              {author.data.top_modules.length === 0 ? (
                <EmptyState title="No modules found" />
              ) : (
                <BarList
                  items={author.data.top_modules.map((m) => ({
                    key: m.name,
                    label: m.name,
                    value: m.touches,
                  }))}
                />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
