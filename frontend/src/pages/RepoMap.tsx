import { useCallback, useState } from "react";
import { api, fileHref } from "../api/client";
import { GraphLegend } from "../components/GraphLegend";
import { GraphView } from "../components/GraphView";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";
import type { GraphNode } from "../api/types";

const SOLE_OWNED_RING = "var(--cat-7)";

const LEGEND_ITEMS = [
  { color: "var(--status-critical)", label: "high risk" },
  { color: "var(--status-warning)", label: "medium risk" },
  { color: "var(--status-good)", label: "low risk" },
  { color: SOLE_OWNED_RING, label: "ring = sole-owned (bus factor 1)" },
];

// weight on a File node here is already risk_score (or risk_score_recent,
// depending on scoreMode) normalized 0-1 against the max among selected
// files (see backend/app/routers/repo.py::get_repo_map). Dashboard's 4-tier
// riskTier() reads great as a text list, but a graph this dense is easier
// to scan with fewer distinct hues -- 3 bands instead, same --status-*
// tokens (reusing the app's severity ramp, not inventing new colors).
function colorForNode(n: GraphNode): string {
  if (n.weight >= 0.66) return "var(--status-critical)";
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
  const map = useApi(useCallback(() => api.repoMap(scoreMode, 40), [scoreMode]));

  return (
    <div className="page-wide">
      <div className="page-header">
        <h1 className="page-title">Repo map</h1>
        <p className="page-subtitle">
          The repo's riskiest files, all at once — not every file, just the ones worth worrying about. Bigger,
          redder circles are riskier (color + size both encode risk score); a violet ring means only one person
          has ever touched that file. A line means two files tend to change together, and more shared commits
          pulls that pair closer together. Hover a file for its exact risk score and whether it's trending worse.
          Drag to rearrange, scroll to zoom, click a file to open it.
        </p>
      </div>

      <div className="card card-pad">
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
              height={640}
              colorForNode={colorForNode}
              strokeForNode={strokeForNode}
              hrefForNode={hrefForNode}
            />
            <GraphLegend items={LEGEND_ITEMS} />
          </>
        )}
      </div>
    </div>
  );
}
