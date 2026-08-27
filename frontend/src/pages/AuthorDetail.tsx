import { useCallback } from "react";
import { useParams } from "react-router-dom";
import { api, fileHref } from "../api/client";
import { BarList } from "../components/BarList";
import { GraphView } from "../components/GraphView";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { StatTile } from "../components/StatTile";
import { useApi } from "../hooks/useApi";

function formatLastTouched(iso: string | null): string {
  if (!iso) return "unknown";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days < 1) return "today";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.round(days / 30)}mo ago`;
  return `${(days / 365).toFixed(1)}y ago`;
}

export function AuthorDetail() {
  const { email = "" } = useParams();
  const author = useApi(useCallback(() => api.author(email), [email]));
  const network = useApi(useCallback(() => api.authorNetwork(email), [email]));

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
              <h2 className="section-title">Collaboration network</h2>
              <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "4px 0 14px" }}>
                Other authors who have touched the same files, weighted by how many files they share — the closest
                nodes are the people most likely to already understand this author's work.
              </p>
              {network.loading && <LoadingRows rows={4} height={30} />}
              {network.error && <ErrorState error={network.error} onRetry={network.reload} />}
              {network.data && network.data.nodes.length <= 1 && (
                <EmptyState title="No collaborators found" subtitle="No other author shares a file with this one." />
              )}
              {network.data && network.data.nodes.length > 1 && (
                <GraphView nodes={network.data.nodes} edges={network.data.edges} />
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

            <div className="card card-pad">
              <h2 className="section-title">At risk if they leave</h2>
              <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "4px 0 14px" }}>
                Files only this author has ever committed to — true bus-factor-1, with nobody else to hand them to.
              </p>
              {network.loading && <LoadingRows rows={4} height={30} />}
              {network.error && <ErrorState error={network.error} onRetry={network.reload} />}
              {network.data && network.data.at_risk_files.length === 0 && (
                <EmptyState title="No sole-owned files" subtitle="Everything this author has touched has at least one other contributor." />
              )}
              {network.data && network.data.at_risk_files.length > 0 && (
                <BarList
                  items={network.data.at_risk_files.map((f) => ({
                    key: f.path,
                    label: f.path,
                    sublabel: `${f.module} · last touched ${formatLastTouched(f.last_touched)}`,
                    value: f.commit_count,
                    href: fileHref(f.path),
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
