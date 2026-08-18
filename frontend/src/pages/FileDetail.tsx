import { useCallback, useState } from "react";
import { useParams } from "react-router-dom";
import { api, fileHref } from "../api/client";
import { BarList } from "../components/BarList";
import { CommitList } from "../components/CommitList";
import { GraphView } from "../components/GraphView";
import { ModuleChip } from "../components/ModuleChip";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { StatTile } from "../components/StatTile";
import { useApi } from "../hooks/useApi";

export function FileDetail() {
  const params = useParams();
  const path = params["*"] ?? "";
  const [depth, setDepth] = useState<1 | 2>(2);

  const detail = useApi(useCallback(() => api.file(path), [path]));
  const blast = useApi(useCallback(() => api.blastRadius(path, depth, 1), [path, depth]));

  if (!path) return <EmptyState title="No file selected" />;

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title mono" style={{ fontSize: 17, wordBreak: "break-all" }}>
          {path}
        </h1>
        {detail.data && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
            <ModuleChip name={detail.data.module} />
            {detail.data.is_deleted && (
              <span className="badge" style={{ color: "var(--status-critical)" }}>
                deleted from HEAD
              </span>
            )}
          </div>
        )}
      </div>

      {detail.loading && <LoadingRows rows={4} height={60} />}
      {detail.error && <ErrorState error={detail.error} onRetry={detail.reload} />}

      {detail.data && (
        <div className="stack">
          <div className="grid grid-stats">
            <StatTile label="Commits touching this file" value={detail.data.commit_count} />
            <StatTile label="Distinct owners" value={detail.data.owners.length} />
            <StatTile label="Coupled files" value={detail.data.co_changes.length} />
            <StatTile
              label="First seen"
              value={detail.data.first_commit_at ? new Date(detail.data.first_commit_at).toLocaleDateString() : "—"}
            />
          </div>

          <div className="card card-pad">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <h2 className="section-title" style={{ margin: 0 }}>
                Blast radius
              </h2>
              <div style={{ display: "flex", gap: 4 }}>
                <button className="btn" onClick={() => setDepth(1)} style={{ borderColor: depth === 1 ? "var(--cat-1)" : undefined }}>
                  1 hop
                </button>
                <button className="btn" onClick={() => setDepth(2)} style={{ borderColor: depth === 2 ? "var(--cat-1)" : undefined }}>
                  2 hops
                </button>
              </div>
            </div>
            <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "4px 0 14px" }}>
              Files that historically change in the same commits as this one — direct coupling (dark) and
              second-degree propagation through those files (light). Drag nodes, scroll to zoom, click to open.
            </p>
            {blast.loading && <LoadingRows rows={6} height={30} />}
            {blast.error && <ErrorState error={blast.error} onRetry={blast.reload} />}
            {blast.data && blast.data.nodes.length <= 1 && (
              <EmptyState title="No coupling detected" subtitle="This file hasn't reliably co-changed with others." />
            )}
            {blast.data && blast.data.nodes.length > 1 && <GraphView nodes={blast.data.nodes} edges={blast.data.edges} />}
          </div>

          <div className="grid grid-2">
            <div className="card card-pad">
              <h2 className="section-title">Co-changed files</h2>
              {detail.data.co_changes.length === 0 ? (
                <EmptyState title="No repeated co-changes" />
              ) : (
                <BarList
                  items={detail.data.co_changes.map((c) => ({
                    key: c.path,
                    label: c.path,
                    sublabel: c.module,
                    value: c.shared_commits,
                    href: fileHref(c.path),
                  }))}
                  formatValue={(v) => `${v}×`}
                />
              )}
            </div>

            <div className="card card-pad">
              <h2 className="section-title">Ownership</h2>
              {detail.data.owners.length === 0 ? (
                <EmptyState title="No commits found" />
              ) : (
                <BarList
                  items={detail.data.owners.map((o) => ({
                    key: o.author_email,
                    label: o.author_name,
                    value: o.commit_count,
                    displayValue: `${Math.round(o.share * 100)}%`,
                  }))}
                />
              )}
            </div>
          </div>

          <div className="card card-pad">
            <h2 className="section-title">Recent commits</h2>
            {detail.data.recent_commits.length === 0 ? (
              <EmptyState title="No commits found" />
            ) : (
              <CommitList commits={detail.data.recent_commits} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
