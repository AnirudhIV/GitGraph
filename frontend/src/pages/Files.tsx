import { useCallback, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, fileHref } from "../api/client";
import { ModuleChip } from "../components/ModuleChip";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";
import { riskColorVar, riskTier } from "../lib/riskColor";

export function Files() {
  const [search, setSearch] = useState("");
  const [searchParams, setSearchParams] = useSearchParams();
  const moduleFilter = searchParams.get("module");
  // A module filter narrows an already-fetched list rather than needing its
  // own endpoint, so fetch more than the default top-80-by-churn to cover
  // modules whose files wouldn't otherwise crack that ranking.
  const files = useApi(useCallback(() => api.files(search, moduleFilter ? 400 : 80), [search, moduleFilter]));
  const visibleFiles = useMemo(
    () => (moduleFilter ? (files.data ?? []).filter((f) => f.module === moduleFilter) : files.data ?? []),
    [files.data, moduleFilter]
  );
  // Same relative grading Dashboard uses (riskTier grades against the max
  // in the *current* list, not a fixed threshold -- risk_score has no
  // universal scale) -- here that's whichever files are currently visible.
  const maxRisk = useMemo(() => Math.max(0, ...visibleFiles.map((f) => f.risk_score ?? 0)), [visibleFiles]);

  return (
    <div className="page-wide page-tight">
      <div className="page-header">
        <h1 className="page-title">Files</h1>
        <p className="page-subtitle">Every file that has appeared in the last N commits, ranked by commit count.</p>
      </div>

      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 20 }}>
        <div style={{ maxWidth: 420, flex: "1 1 260px" }}>
          <input
            type="search"
            placeholder="Filter by path…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {moduleFilter && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Filtered by</span>
            <ModuleChip name={moduleFilter} />
            <button
              className="btn"
              style={{ padding: "2px 8px", fontSize: 11 }}
              onClick={() =>
                setSearchParams((prev) => {
                  prev.delete("module");
                  return prev;
                })
              }
            >
              clear
            </button>
          </span>
        )}
      </div>

      <div className="card card-pad">
        {files.loading && <LoadingRows rows={10} />}
        {files.error && <ErrorState error={files.error} onRetry={files.reload} />}
        {files.data && visibleFiles.length === 0 && (
          <EmptyState
            title="No files match"
            subtitle={moduleFilter ? `No files found in module "${moduleFilter}".` : "Try a different search, or check the seed script ran."}
          />
        )}
        {visibleFiles.length > 0 && (
          <div>
            {visibleFiles.map((f) => (
              <Link key={f.path} to={fileHref(f.path)} className="link-row">
                <div style={{ minWidth: 0 }}>
                  <div className="row-primary">{f.path}</div>
                  <div style={{ marginTop: 4 }}>
                    <ModuleChip name={f.module} />
                  </div>
                </div>
                <div className="row-secondary" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  {f.is_deleted && <span style={{ color: "var(--status-critical)" }}>deleted</span>}
                  <span>{f.commit_count} commits</span>
                  {f.risk_score != null && (
                    <span style={{ color: riskColorVar(riskTier(f.risk_score, maxRisk)), fontWeight: 600 }}>
                      risk {f.risk_score.toFixed(2)}
                    </span>
                  )}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
