import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fileHref, functionHref } from "../api/client";
import { BarList } from "../components/BarList";
import { CommitList } from "../components/CommitList";
import { GraphView } from "../components/GraphView";
import { ModuleChip } from "../components/ModuleChip";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { StatTile } from "../components/StatTile";
import { useApi } from "../hooks/useApi";
import { riskColorVar, riskTier } from "../lib/riskColor";

// Same idiom RepoMap.tsx uses for confidence-independent graphs elsewhere:
// a low-confidence (best-effort name match, not a type-checked/same-file
// resolution) call edge is dashed rather than solid, so a viewer can tell
// "this edge is a guess" apart from "this edge is certain" at a glance.
function edgeStyleForLink(e: { confidence?: string }): { dash?: string } {
  return { dash: e.confidence === "low" ? "4 3" : undefined };
}

export function FileDetail() {
  const params = useParams();
  const path = params["*"] ?? "";
  const [depth, setDepth] = useState<1 | 2>(2);

  const detail = useApi(useCallback(() => api.file(path), [path]));
  const blast = useApi(useCallback(() => api.blastRadius(path, depth, 1), [path, depth]));
  const functions = useApi(useCallback(() => api.fileFunctions(path), [path]));
  const callGraph = useApi(useCallback(() => api.fileCallGraph(path), [path]));
  // riskTier() grades relative to the max score in a list (see lib/riskColor.ts),
  // and there's no natural "list" on a single-file page -- top-1 hotspot gives
  // the repo's current max so this file's severity still reads the same way
  // Dashboard's does, not an invented absolute threshold.
  const topHotspot = useApi(useCallback(() => api.hotspots(1), []));

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
            {detail.data.renamed_to ? (
              <span className="badge" style={{ color: "var(--status-warning)" }}>
                renamed to{" "}
                <Link to={fileHref(detail.data.renamed_to)} className="mono">
                  {detail.data.renamed_to}
                </Link>
              </span>
            ) : (
              detail.data.is_deleted && (
                <span className="badge" style={{ color: "var(--status-critical)" }}>
                  deleted from HEAD
                </span>
              )
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
            {detail.data.risk_score != null ? (
              <StatTile
                label="Risk score"
                value={detail.data.risk_score.toFixed(2)}
                sublabel={
                  topHotspot.data && topHotspot.data[0]
                    ? riskTier(detail.data.risk_score, topHotspot.data[0].risk_score) + " · vs. repo's riskiest"
                    : undefined
                }
                valueColor={
                  topHotspot.data && topHotspot.data[0]
                    ? riskColorVar(riskTier(detail.data.risk_score, topHotspot.data[0].risk_score))
                    : undefined
                }
              />
            ) : (
              <StatTile label="Risk score" value="—" sublabel="not enough commits to score" />
            )}
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
              Files that historically change in the same commits as this one. Color shows how many hops from the
              selected file (see the legend below the graph). A line means two files were touched in the same
              commit — more shared commits pulls that pair closer together. Drag nodes, scroll to zoom, click to
              open.
            </p>
            {blast.loading && <LoadingRows rows={6} height={30} />}
            {blast.error && <ErrorState error={blast.error} onRetry={blast.reload} />}
            {blast.data && blast.data.nodes.length <= 1 && (
              <EmptyState title="No coupling detected" subtitle="This file hasn't reliably co-changed with others." />
            )}
            {blast.data && blast.data.nodes.length > 1 && (
              <GraphView nodes={blast.data.nodes} edges={blast.data.edges} />
            )}
          </div>

          {functions.data && functions.data.length > 0 && (
            <div className="card card-pad">
              <h2 className="section-title">Functions in this file</h2>
              <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "4px 0 14px" }}>
                Parsed from source, not git history -- ranked by importance (how many places call it), not reading
                order. Dashed graph lines are best-effort name matches (low confidence); solid lines are resolved
                via same-file or real type-checked/import analysis.
              </p>
              <BarList
                items={functions.data.map((f) => ({
                  key: f.id,
                  label: f.qualname,
                  sublabel: `L${f.start_line} · ${f.language}${f.is_exported ? " · exported" : ""}`,
                  value: f.caller_count,
                  href: functionHref(f.id),
                  displayValue: `${f.caller_count} callers`,
                }))}
              />
              {callGraph.data && callGraph.data.nodes.length > 1 && (
                <div style={{ marginTop: 14 }}>
                  <GraphView
                    nodes={callGraph.data.nodes}
                    edges={callGraph.data.edges}
                    height={360}
                    hrefForNode={(n) => functionHref(n.id)}
                    edgeStyleForLink={edgeStyleForLink}
                    directed
                  />
                </div>
              )}
            </div>
          )}

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
