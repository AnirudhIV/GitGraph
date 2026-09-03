import { useCallback, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fileHref, functionHref } from "../api/client";
import { BarList } from "../components/BarList";
import { GraphView } from "../components/GraphView";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { StatTile } from "../components/StatTile";
import { useApi } from "../hooks/useApi";

// Same confidence-to-dash mapping as FileDetail.tsx's own call graph card --
// kept local rather than shared, matching how RepoMap.tsx and FileDetail.tsx
// each already define their own small GraphView styling helpers rather than
// factoring out a one-line function.
function edgeStyleForLink(e: { confidence?: string }): { dash?: string } {
  return { dash: e.confidence === "low" ? "4 3" : undefined };
}

export function FunctionDetail() {
  const params = useParams();
  const id = params.id ? decodeURIComponent(params.id) : "";
  const [depth, setDepth] = useState<1 | 2>(2);

  const detail = useApi(useCallback(() => api.function(id), [id]));
  const graph = useApi(useCallback(() => api.functionCallGraph(id, depth), [id, depth]));

  if (!id) return <EmptyState title="No function selected" />;

  return (
    <div>
      <div className="page-header">
        {detail.data && (
          <>
            <h1 className="page-title mono" style={{ fontSize: 17, wordBreak: "break-all" }}>
              {detail.data.qualname}
            </h1>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
              <span className="badge">{detail.data.language}</span>
              {detail.data.is_exported && <span className="badge">exported</span>}
              {detail.data.is_method && <span className="badge">method</span>}
              <Link to={fileHref(detail.data.path)} className="mono" style={{ fontSize: 12.5 }}>
                {detail.data.path}:{detail.data.start_line}
              </Link>
            </div>
          </>
        )}
      </div>

      {detail.loading && <LoadingRows rows={4} height={60} />}
      {detail.error && <ErrorState error={detail.error} onRetry={detail.reload} />}

      {detail.data && (
        <div className="stack">
          <div className="grid grid-stats">
            <StatTile label="Callers" value={detail.data.callers.length} />
            <StatTile label="Callees" value={detail.data.callees.length} />
            <StatTile
              label="Lines"
              value={detail.data.end_line - detail.data.start_line + 1}
              sublabel={`L${detail.data.start_line}-${detail.data.end_line}`}
            />
          </div>

          <div className="card card-pad">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <h2 className="section-title" style={{ margin: 0 }}>
                Call graph
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
              Parsed from source, not git history. Direct callers and callees of this function, one hop in each
              direction (or two, with "2 hops"). Dashed lines are best-effort name matches; solid lines are
              same-file or real type-checked/import resolutions. Click a node to open that function.
            </p>
            {graph.loading && <LoadingRows rows={6} height={30} />}
            {graph.error && <ErrorState error={graph.error} onRetry={graph.reload} />}
            {graph.data && graph.data.nodes.length <= 1 && (
              <EmptyState title="No calls detected" subtitle="This function has no resolved callers or callees." />
            )}
            {graph.data && graph.data.nodes.length > 1 && (
              <GraphView
                nodes={graph.data.nodes}
                edges={graph.data.edges}
                hrefForNode={(n) => functionHref(n.id)}
                edgeStyleForLink={edgeStyleForLink}
                directed
              />
            )}
          </div>

          <div className="grid grid-2">
            <div className="card card-pad">
              <h2 className="section-title">Callers</h2>
              {detail.data.callers.length === 0 ? (
                <EmptyState title="No callers found" />
              ) : (
                <BarList
                  items={detail.data.callers.map((c) => ({
                    key: c.id,
                    label: c.name,
                    sublabel: `${c.path} · ${c.confidence} confidence`,
                    value: c.call_count,
                    href: functionHref(c.id),
                  }))}
                  formatValue={(v) => `${v}×`}
                />
              )}
            </div>

            <div className="card card-pad">
              <h2 className="section-title">Callees</h2>
              {detail.data.callees.length === 0 ? (
                <EmptyState title="No callees found" />
              ) : (
                <BarList
                  items={detail.data.callees.map((c) => ({
                    key: c.id,
                    label: c.name,
                    sublabel: `${c.path} · ${c.confidence} confidence`,
                    value: c.call_count,
                    href: functionHref(c.id),
                  }))}
                  formatValue={(v) => `${v}×`}
                />
              )}
            </div>
          </div>

          {detail.data.source && (
            <div className="card card-pad">
              <h2 className="section-title">Source</h2>
              <pre
                className="mono"
                style={{
                  margin: "8px 0 0",
                  padding: 12,
                  overflowX: "auto",
                  fontSize: 12.5,
                  lineHeight: 1.5,
                  background: "var(--surface-page)",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border)",
                }}
              >
                <code>{detail.data.source}</code>
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
