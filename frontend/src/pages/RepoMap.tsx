import { useCallback, useState } from "react";
import { api, fileHref } from "../api/client";
import { GraphLegend } from "../components/GraphLegend";
import { GraphView } from "../components/GraphView";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";
import type { GraphNode } from "../api/types";

const SOLE_OWNED_RING = "var(--cat-7)";

// --status-critical reads as a soft, pinkish red -- fine as a small text
// label elsewhere, but too washed out to read as "highest severity" on a
// bubble that's also competing with the warning/good tiers on this graph.
// A local, more saturated red just for this graph's top tier, rather than
// changing --status-critical itself and shifting every other page that
// reuses it (Dashboard, Files, FileDetail) for a look that only this graph
// wanted.
const HIGH_RISK_RED = "#e5342b";

const LEGEND_ITEMS = [
  { color: HIGH_RISK_RED, label: "high risk" },
  { color: "var(--status-warning)", label: "medium risk" },
  { color: "var(--status-good)", label: "low risk" },
  { color: SOLE_OWNED_RING, label: "ring = sole-owned (bus factor 1)" },
];

// weight on a File node here is already risk_score (or risk_score_recent,
// depending on scoreMode) normalized 0-1 against the max among selected
// files (see backend/app/routers/repo.py::get_repo_map). Dashboard's 4-tier
// riskTier() reads great as a text list, but a graph this dense is easier
// to scan with fewer distinct hues -- 3 bands instead, same --status-*
// tokens (reusing the app's severity ramp, not inventing new colors) except
// for the top tier -- see HIGH_RISK_RED above.
function colorForNode(n: GraphNode): string {
  if (n.weight >= 0.66) return HIGH_RISK_RED;
  if (n.weight >= 0.33) return "var(--status-warning)";
  return "var(--status-good)";
}

// Second, independent color channel from colorForNode: sole-ownership is a
// categorically different kind of danger (nobody else can review a change
// to this file) than risk severity, so it gets its own ring color instead
// of being folded into -- or fighting with -- the fill color.
function strokeForNode(n: GraphNode): string {
  return n.sole_owned ? SOLE_OWNED_RING : colorForNode(n);
}

function hrefForNode(n: GraphNode): string {
  return fileHref(n.id);
}

export function RepoMap() {
  const [scoreMode, setScoreMode] = useState<"all-time" | "recent">("all-time");
  // 100 is the API's own ceiling (backend/app/routers/repo.py::get_repo_map,
  // top_n: le=100) -- every file that clears the risk-score bar (see the
  // backend's min-commits + real-coupling gate) is still filtered down to
  // this rank regardless, so bumping past 100 would need that ceiling
  // raised too, not just this call.
  const map = useApi(useCallback(() => api.repoMap(scoreMode, 100), [scoreMode]));

  return (
    <div className="page-wide">
      <div className="page-header">
        <h1 className="page-title">Repo map</h1>
        <p className="page-subtitle">
          The repo's riskiest files, not every file. Position = coupling: a line means two files tend to change
          together, and the more often, the closer they're pulled — a tight cluster is a real group of files that
          move together. Color and size = risk score instead, a separate signal; a violet ring means only one
          person has ever touched that file. Hover for exact risk score, drag to rearrange, scroll to zoom, click
          to open a file.
        </p>
      </div>

      <div className="card-pad">
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 4, marginBottom: 4 }}>
          <button
            className="btn"
            onClick={() => setScoreMode("all-time")}
            style={{ borderColor: scoreMode === "all-time" ? "var(--cat-1)" : undefined }}
          >
            All-time
          </button>
          <button
            className="btn"
            onClick={() => setScoreMode("recent")}
            style={{ borderColor: scoreMode === "recent" ? "var(--cat-1)" : undefined }}
          >
            Recent
          </button>
        </div>
        {map.loading && <LoadingRows rows={8} height={40} />}
        {map.error && <ErrorState error={map.error} onRetry={map.reload} />}
        {map.data && map.data.nodes.length === 0 && (
          <EmptyState title="Nothing to map yet" subtitle="Run the seed script to load a repository's history." />
        )}
        {map.data && map.data.nodes.length > 0 && (
          <>
            <GraphView
              nodes={map.data.nodes}
              edges={map.data.edges}
              height={820}
              colorForNode={colorForNode}
              strokeForNode={strokeForNode}
              hrefForNode={hrefForNode}
              // Same tuning Collaboration's team-topology graph uses (see
              // Collaboration.tsx): both graphs are the same shape --
              // unanchored nodes (every node hop:1, no hub) positioned
              // purely by edge weight (there: shared_files: coupling
              // density here). Without this, weight barely differentiates
              // link distance and every pair reads about equally close;
              // spacingScale pushes uncoupled files apart while
              // clusterSensitivity makes strongly-coupled pairs pull in
              // dramatically closer, so real coupling clusters actually
              // read as tight instead of the whole graph looking uniformly
              // loose.
              spacingScale={1.7}
              clusterSensitivity={2.8}
            />
            <GraphLegend items={LEGEND_ITEMS} />
          </>
        )}
      </div>
    </div>
  );
}
