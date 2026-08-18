import { useCallback } from "react";
import { api } from "../api/client";
import { ModuleChip } from "../components/ModuleChip";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";

export function Modules() {
  const modules = useApi(useCallback(() => api.modules(), []));
  const coupling = useApi(useCallback(() => api.moduleCoupling(20), []));

  return (
    <div>
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
          <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "0 0 12px" }}>
            Module pairs whose files were touched in the same commit most often — the file-level co-change graph
            rolled up one level.
          </p>
          {coupling.loading && <LoadingRows rows={6} />}
          {coupling.error && <ErrorState error={coupling.error} onRetry={coupling.reload} />}
          {coupling.data && coupling.data.length === 0 && (
            <EmptyState title="No cross-module coupling found" subtitle="This repo's modules change independently." />
          )}
          {coupling.data && coupling.data.length > 0 && (
            <div className="stack" style={{ gap: 10 }}>
              {coupling.data.map((c, i) => (
                <div key={i} className="link-row">
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <ModuleChip name={c.module_a} />
                    <span style={{ color: "var(--text-muted)" }}>↔</span>
                    <ModuleChip name={c.module_b} />
                  </div>
                  <div className="row-secondary mono">{c.shared_commits} shared commits</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
