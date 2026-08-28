import { useCallback } from "react";
import { api, moduleHref } from "../api/client";
import { GraphLegend } from "../components/GraphLegend";
import { GraphView } from "../components/GraphView";
import { ModuleChip, moduleColorVar } from "../components/ModuleChip";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";
import type { GraphNode } from "../api/types";

export function Modules() {
  const modules = useApi(useCallback(() => api.modules(), []));
  const graph = useApi(useCallback(() => api.moduleGraph(40), []));

  return (
    <div className="page-wide">
      <div className="page-header">
        <h1 className="page-title">Modules</h1>
        <p className="page-subtitle">
          Top-level directories, rolled up from file-level activity. Module coupling shows which parts of the
          system change together at the architectural level.
        </p>
      </div>

      <div className="stack">
        <div className="card card-pad">
          <h2 className="section-title">All modules</h2>
          {modules.loading && <LoadingRows rows={6} />}
          {modules.error && <ErrorState error={modules.error} onRetry={modules.reload} />}
          {modules.data && modules.data.length === 0 && <EmptyState title="No modules found" />}
          {modules.data && modules.data.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Module</th>
                  <th>Files</th>
                  <th>Commits</th>
                  <th>Authors</th>
                </tr>
              </thead>
              <tbody>
                {modules.data.map((m) => (
                  <tr key={m.name}>
                    <td>
                      <ModuleChip name={m.name} />
                    </td>
                    <td className="mono">{m.file_count}</td>
                    <td className="mono">{m.commit_count}</td>
                    <td className="mono">{m.author_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card card-pad">
          <h2 className="section-title">Module coupling</h2>
          <p style={{ fontSize: 13.5, color: "var(--text-muted)", margin: "0 0 12px" }}>
            Module pairs whose files were touched in the same commit most often — the file-level co-change graph
            rolled up one level. Color is each module's identity (see the legend below). Bigger circles had more
            total coupling activity; a line means two modules' files changed together, and more shared commits
            pulls that pair closer together. Drag nodes, scroll to zoom, click a module to see its files.
          </p>
          {graph.loading && <LoadingRows rows={6} />}
          {graph.error && <ErrorState error={graph.error} onRetry={graph.reload} />}
          {graph.data && graph.data.nodes.length === 0 && (
            <EmptyState title="No cross-module coupling found" subtitle="This repo's modules change independently." />
          )}
          {graph.data && graph.data.nodes.length > 0 && (
            <>
              <GraphView
                nodes={graph.data.nodes}
                edges={graph.data.edges}
                colorForNode={(n: GraphNode) => moduleColorVar(n.id)}
                hrefForNode={(n: GraphNode) => moduleHref(n.id)}
              />
              <GraphLegend
                items={[{ color: ["var(--cat-1)", "var(--cat-3)", "var(--cat-5)"], label: "colored by module identity" }]}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
