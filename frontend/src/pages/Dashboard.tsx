import { useCallback } from "react";
import { Link } from "react-router-dom";
import { api, fileHref } from "../api/client";
import { ModuleChip } from "../components/ModuleChip";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { StatTile } from "../components/StatTile";
import { useApi } from "../hooks/useApi";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

export function Dashboard() {
  const stats = useApi(useCallback(() => api.stats(), []));
  const hotspots = useApi(useCallback(() => api.hotspots(12), []));

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Repository overview</h1>
        <p className="page-subtitle">
          A graph of every commit, author and file in the repository's history — mined with{" "}
          <code>git log --numstat</code> and loaded into CognoDB. Explore coupling, ownership and risk below.
        </p>
      </div>

      <div className="stack">
        <section>
          {stats.loading && <div className="grid grid-stats"><LoadingRows rows={4} height={72} /></div>}
          {stats.error && <ErrorState error={stats.error} onRetry={stats.reload} />}
          {stats.data && (
            <div className="grid grid-stats">
              <StatTile label="Files tracked" value={stats.data.file_count.toLocaleString()} />
              <StatTile label="Commits" value={stats.data.commit_count.toLocaleString()} />
              <StatTile label="Authors" value={stats.data.author_count.toLocaleString()} />
              <StatTile label="Modules" value={stats.data.module_count.toLocaleString()} />
              <StatTile
                label="History span"
                value={formatDate(stats.data.first_commit_at)}
                sublabel={`through ${formatDate(stats.data.last_commit_at)}`}
              />
            </div>
          )}
        </section>

        <section className="card card-pad">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
            <h2 className="section-title" style={{ margin: 0 }}>
              Hotspots — highest risk files
            </h2>
          </div>
          <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "0 0 12px" }}>
            Ranked by commit churn × coupling fan-out ÷ bus factor — files that change often, drag other files
            along with them, and are known to few people.
          </p>
          {hotspots.loading && <LoadingRows rows={6} />}
          {hotspots.error && <ErrorState error={hotspots.error} onRetry={hotspots.reload} />}
          {hotspots.data && hotspots.data.length === 0 && (
            <EmptyState title="No hotspots yet" subtitle="Run the seed script to load a repository's history." />
          )}
          {hotspots.data && hotspots.data.length > 0 && (
            <div className="stack" style={{ gap: 10 }}>
              {hotspots.data.map((h) => (
                <Link key={h.path} to={fileHref(h.path)} className="link-row" style={{ padding: "10px 0" }}>
                  <div style={{ minWidth: 0 }}>
                    <div className="row-primary">{h.path}</div>
                    <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center" }}>
                      <ModuleChip name={h.module} />
                      <span className="row-secondary">
                        {h.commit_count} commits · {h.coupled_file_count} coupled files · {h.author_count} author
                        {h.author_count === 1 ? "" : "s"}
                      </span>
                    </div>
                  </div>
                  <div style={{ fontVariantNumeric: "tabular-nums", fontWeight: 600, color: "var(--status-serious)" }}>
                    {h.risk_score.toFixed(2)}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
