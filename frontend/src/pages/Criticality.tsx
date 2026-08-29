import { useCallback } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";
import { riskColorVar, riskTier } from "../lib/riskColor";

export function Criticality() {
  const criticality = useApi(useCallback(() => api.authorCriticality(50), []));

  return (
    <div className="page-wide">
      <div className="page-header">
        <h1 className="page-title">Criticality</h1>
        <p className="page-subtitle">
          A formalized bus-factor: who'd hurt the most to lose, not just who commits the most. For every file an
          author is concentrated on (≥75% of its commits are theirs), the file's own risk score counts toward
          their total, boosted further if they're the sole committer — plus a flat floor per sole-owned file even
          when it has no risk score, since a quiet, rarely-touched file only one person understands is still a
          real risk, independent of how often it churns.
        </p>
      </div>

      <div className="card card-pad">
        {criticality.loading && <LoadingRows rows={8} height={44} />}
        {criticality.error && <ErrorState error={criticality.error} onRetry={criticality.reload} />}
        {criticality.data && criticality.data.length === 0 && (
          <EmptyState title="No concentrated ownership yet" subtitle="No author is concentrated enough on any file to register." />
        )}
        {criticality.data && criticality.data.length > 0 && (
          <div className="stack" style={{ gap: 8 }}>
            {(() => {
              const maxScore = Math.max(...criticality.data.map((a) => a.criticality_score));
              return criticality.data.map((a) => {
                const tier = riskTier(a.criticality_score, maxScore);
                const color = riskColorVar(tier);
                return (
                  <Link
                    key={a.email}
                    to={`/authors/${encodeURIComponent(a.email)}`}
                    className="link-row"
                    style={{ borderLeft: `3px solid ${color}`, paddingLeft: 12 }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div className="row-primary">{a.name}</div>
                      <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center" }}>
                        <span className="row-secondary">
                          {a.sole_owned_file_count} sole-owned file{a.sole_owned_file_count === 1 ? "" : "s"}
                        </span>
                        {a.is_stale && (
                          <span
                            className="badge"
                            style={{ borderColor: "var(--status-warning)", color: "var(--status-warning)", fontSize: 11 }}
                          >
                            inactive 6mo+
                          </span>
                        )}
                      </div>
                    </div>
                    <div style={{ textAlign: "right", flex: "none" }}>
                      <div
                        style={{
                          fontVariantNumeric: "tabular-nums",
                          fontSize: 24,
                          fontWeight: 700,
                          lineHeight: 1,
                          letterSpacing: "-0.01em",
                          color,
                        }}
                      >
                        {a.criticality_score.toFixed(2)}
                      </div>
                      <div
                        style={{
                          fontSize: 10,
                          fontWeight: 600,
                          textTransform: "uppercase",
                          letterSpacing: "0.05em",
                          color: "var(--text-muted)",
                          marginTop: 3,
                        }}
                      >
                        criticality
                      </div>
                    </div>
                  </Link>
                );
              });
            })()}
          </div>
        )}
      </div>
    </div>
  );
}
