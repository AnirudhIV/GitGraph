import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, functionHref } from "../api/client";
import { GraphLegend } from "../components/GraphLegend";
import { GraphView } from "../components/GraphView";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";
import { riskColorVar, riskTier } from "../lib/riskColor";
import type { GraphNode } from "../api/types";

// Color by language for the graph above -- the repo-wide map is about
// centrality/structure, not risk, so language (the one categorical fact
// every Function node carries) is the more useful thing to distinguish at
// a glance there. The list below is where risk_score (a real per-function
// metric now: log1p(change_count) * log1p(caller_count)) gets its own
// column and its own sort, same riskColorVar/riskTier treatment Files.tsx
// already uses for file-level risk.
const LANGUAGE_COLOR: Record<string, string> = {
  python: "var(--cat-1)",
  typescript: "#238636",
  javascript: "#f2c14e",
};

function colorForNode(n: GraphNode): string {
  return LANGUAGE_COLOR[n.group] ?? "var(--text-muted)";
}

function edgeStyleForLink(e: { confidence?: string }): { dash?: string } {
  return { dash: e.confidence === "low" ? "4 3" : undefined };
}

const LEGEND_ITEMS = [
  { color: LANGUAGE_COLOR.python, label: "python" },
  { color: LANGUAGE_COLOR.typescript, label: "typescript" },
  { color: LANGUAGE_COLOR.javascript, label: "javascript" },
];

export function Functions() {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"callers" | "risk">("callers");
  const map = useApi(useCallback(() => api.functionMap(60), []));
  const list = useApi(useCallback(() => api.functions(search, sort), [search, sort]));
  // Same relative-grading idiom Files.tsx uses for file-level risk_score --
  // there's no universal scale for this metric either, so color is graded
  // against the max in the *current* list, not a fixed threshold.
  const maxRisk = useMemo(() => Math.max(0, ...(list.data ?? []).map((f) => f.risk_score)), [list.data]);

  return (
    <div className="page-wide page-tight">
      <div className="page-header">
        <h1 className="page-title">Functions</h1>
        <p className="page-subtitle">
          Parsed from source, not git history -- a call graph of functions across the repo. The graph above shows
          the most-called functions and how they call each other; the list below is every parsed function,
          searchable. Dashed lines are best-effort name matches (low confidence); solid lines are same-file or real
          type-checked/import resolutions. Click a node or row to open that function's own call graph.
        </p>
      </div>

      <div className="card card-pad" style={{ marginBottom: 20 }}>
        <h2 className="section-title">Most-called functions</h2>
        {map.loading && <LoadingRows rows={8} height={40} />}
        {map.error && <ErrorState error={map.error} onRetry={map.reload} />}
        {map.data && map.data.nodes.length === 0 && (
          <EmptyState
            title="No function calls resolved yet"
            subtitle="Run the seed script against a repo with parseable Python or TypeScript/JavaScript source."
          />
        )}
        {map.data && map.data.nodes.length > 0 && (
          <>
            <GraphView
              nodes={map.data.nodes}
              edges={map.data.edges}
              height={640}
              colorForNode={colorForNode}
              hrefForNode={(n) => functionHref(n.id)}
              edgeStyleForLink={edgeStyleForLink}
              spacingScale={1.5}
              clusterSensitivity={2.2}
              directed
            />
            <GraphLegend items={LEGEND_ITEMS} />
          </>
        )}
      </div>

      <div className="page-header">
        <h2 className="section-title" style={{ margin: 0 }}>
          All functions
        </h2>
        <p className="page-subtitle" style={{ margin: "6px 0 0" }}>
          Risk score combines how often a function has actually changed with how many places call it — log-scaled
          on both, and multiplicative, so a function needs to be both frequently altered and widely depended-on to
          rank high. Called constantly but stable, or edited often but nothing depends on it, both score low.
        </p>
      </div>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 16 }}>
        <div style={{ maxWidth: 420, flex: "1 1 260px" }}>
          <input
            type="search"
            placeholder="Filter by name or path…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Sort by</span>
          {(["callers", "risk"] as const).map((s) => (
            <button
              key={s}
              className="btn"
              onClick={() => setSort(s)}
              style={{
                padding: "4px 10px",
                fontSize: 12,
                fontWeight: sort === s ? 700 : 400,
                borderColor: sort === s ? "var(--cat-1)" : undefined,
                color: sort === s ? "var(--cat-1)" : undefined,
              }}
            >
              {s === "callers" ? "number of callers" : "risk score"}
            </button>
          ))}
        </div>
      </div>

      <div className="card card-pad">
        {list.loading && <LoadingRows rows={10} />}
        {list.error && <ErrorState error={list.error} onRetry={list.reload} />}
        {list.data && list.data.length === 0 && <EmptyState title="No functions match" />}
        {list.data && list.data.length > 0 && (
          <div>
            {list.data.map((f) => (
              <Link key={f.id} to={functionHref(f.id)} className="link-row">
                <div style={{ minWidth: 0 }}>
                  <div className="row-primary mono">{f.qualname}</div>
                  <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 2 }}>{f.path}</div>
                </div>
                <div className="row-secondary" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span className="badge">{f.language}</span>
                  <span>{f.caller_count} callers</span>
                  <span style={{ color: riskColorVar(riskTier(f.risk_score, maxRisk)), fontWeight: 600 }}>
                    risk {f.risk_score.toFixed(2)}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
