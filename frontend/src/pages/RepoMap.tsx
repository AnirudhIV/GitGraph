import { useCallback } from "react";
import { api, fileHref } from "../api/client";
import { GraphLegend } from "../components/GraphLegend";
import { GraphView } from "../components/GraphView";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";
import type { GraphNode } from "../api/types";

const LEGEND_ITEMS = [
  { color: "var(--status-critical)", label: "high risk" },
  { color: "var(--status-warning)", label: "medium risk" },
  { color: "var(--status-good)", label: "low risk" },
];

// weight on a File node here is already risk_score normalized 0-1 against
// the max among included files (see backend/app/routers/repo.py::
// get_repo_map). Dashboard's 4-tier riskTier() reads great as a text list,
// but a graph this dense is easier to scan with fewer distinct hues -- 3
// bands instead, same --status-* tokens (reusing the app's severity ramp,
// not inventing new colors), just fewer of them.
function colorForNode(n: GraphNode): string {
  if (n.weight >= 0.66) return "var(--status-critical)";
  if (n.weight >= 0.33) return "var(--status-warning)";
  return "var(--status-good)";
}

function hrefForNode(n: GraphNode): string {
  return fileHref(n.id);
}

export function RepoMap() {
  const map = useApi(useCallback(() => api.repoMap(50), []));

  return (
    <div className="page-wide">
      <div className="page-header">
        <h1 className="page-title">Repo map</h1>
        <p className="page-subtitle">
          Files that tend to change together, across the whole codebase at once — not just one file's neighborhood.
          A line means two files keep showing up in the same commits. Bigger, redder circles are riskier files.
          Drag to rearrange, scroll to zoom, click a file to open it.
        </p>
      </div>

      <div className="card card-pad">
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
              hrefForNode={hrefForNode}
            />
            <GraphLegend items={LEGEND_ITEMS} />
          </>
        )}
      </div>
    </div>
  );
}
