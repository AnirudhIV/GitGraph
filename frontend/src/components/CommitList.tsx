import type { RecentCommit } from "../api/types";

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

export function CommitList({ commits }: { commits: RecentCommit[] }) {
  return (
    <div>
      {commits.map((c) => (
        <div key={c.hash} className="link-row" style={{ alignItems: "flex-start" }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {c.message || <span style={{ color: "var(--text-muted)" }}>(no message)</span>}
            </div>
            <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 2 }}>
              <span className="mono">{c.hash.slice(0, 7)}</span> · {c.author_name} · {formatDate(c.timestamp)}
            </div>
          </div>
          <div className="row-secondary mono" style={{ textAlign: "right" }}>
            <span style={{ color: "var(--status-good)" }}>+{c.additions}</span>{" "}
            <span style={{ color: "var(--status-critical)" }}>-{c.deletions}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
