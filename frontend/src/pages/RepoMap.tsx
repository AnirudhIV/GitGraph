import { useCallback } from "react";
import { api, fileHref, moduleHref } from "../api/client";
import { GraphLegend } from "../components/GraphLegend";
import { GraphView } from "../components/GraphView";
import { moduleColorVar } from "../components/ModuleChip";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";
import { riskColorVar, riskTier } from "../lib/riskColor";
import type { GraphNode } from "../api/types";

const LEGEND_ITEMS = [
  { color: "var(--status-critical)", label: "critical risk file" },
  { color: "var(--status-serious)", label: "serious risk file" },
  { color: "var(--status-warning)", label: "warning risk file" },
  { color: "var(--status-good)", label: "low risk file" },
  { color: ["var(--cat-1)", "var(--cat-3)", "var(--cat-5)"], label: "module — colored by identity" },
];

// weight on a File node here is already risk_score normalized to the max
// among included files (see backend/app/routers/repo.py::get_repo_map), so
// riskTier(weight, 1) grades it exactly the way Dashboard grades risk_score
// against the list's own max -- just with that division already done.
function colorForNode(n: GraphNode): string {
  if (n.kind === "Module") return moduleColorVar(n.id);
  return riskColorVar(riskTier(n.weight, 1));
}

function hrefForNode(n: GraphNode): string {
  return n.kind === "Module" ? moduleHref(n.id) : fileHref(n.id);
}

export function RepoMap() {
  const map = useApi(useCallback(() => api.repoMap(5), []));

  return (
    <div className="page-wide">
      <div className="page-header">
        <h1 className="page-title">Repo map</h1>
        <p className="page-subtitle">
          The whole repo at once, unanchored — every module, and each module's riskiest files. Modules are colored
          by identity, files by risk score. Drag nodes, scroll to zoom, click through into the file or module.
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
