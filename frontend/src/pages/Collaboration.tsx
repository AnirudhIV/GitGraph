import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api, authorHref, fileHref } from "../api/client";
import { GraphLegend } from "../components/GraphLegend";
import { GraphView } from "../components/GraphView";
import { moduleColorVar } from "../components/ModuleChip";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";
import type { AuthorSummary, GraphNode } from "../api/types";

function topologyColor(n: GraphNode): string {
  return moduleColorVar(n.group || "unassigned");
}

function topologyHref(n: GraphNode): string {
  return authorHref(n.id);
}

function AuthorPicker({
  label,
  value,
  onChange,
}: {
  label: string;
  value: AuthorSummary | null;
  onChange: (a: AuthorSummary | null) => void;
}) {
  const [query, setQuery] = useState("");
  const results = useApi(useCallback(() => (query.length > 1 ? api.authors(query, 8) : Promise.resolve([])), [query]));

  return (
    <div style={{ flex: 1, minWidth: 220 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6 }}>{label}</div>
      {value ? (
        <div className="badge" style={{ padding: "8px 12px", fontSize: 13, justifyContent: "space-between", width: "100%" }}>
          {value.name}
          <button className="btn" style={{ padding: "2px 8px", fontSize: 11 }} onClick={() => onChange(null)}>
            change
          </button>
        </div>
      ) : (
        <div style={{ position: "relative" }}>
          <input type="text" placeholder="Type a name…" value={query} onChange={(e) => setQuery(e.target.value)} />
          {results.data && results.data.length > 0 && (
            <div className="card" style={{ position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, zIndex: 10, maxHeight: 220, overflowY: "auto" }}>
              {results.data.map((a) => (
                <div
                  key={a.email}
                  onClick={() => {
                    onChange(a);
                    setQuery("");
                  }}
                  style={{ padding: "8px 12px", cursor: "pointer", fontSize: 13 }}
                >
                  {a.name} <span style={{ color: "var(--text-muted)", fontSize: 11.5 }}>{a.commit_count} commits</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function Collaboration() {
  const [a, setA] = useState<AuthorSummary | null>(null);
  const [b, setB] = useState<AuthorSummary | null>(null);

  const path = useApi(
    useCallback(() => (a && b ? api.collabPath(a.email, b.email) : Promise.resolve(null)), [a, b])
  );
  const topology = useApi(useCallback(() => api.authorTopology(), []));

  return (
    <div className="page-wide page-tight">
      <div className="page-header">
        <h1 className="page-title">Collaboration</h1>
        <p className="page-subtitle">
          Trace a path between two specific people, or see the whole team's shape at once below.
        </p>
      </div>

      <div className="card card-pad" style={{ marginBottom: 20 }}>
        <h2 className="section-title">Team topology</h2>
        <p style={{ fontSize: 13, color: "var(--text-muted)", margin: "0 0 12px" }}>
          The most active contributors. What groups people together (their position, not their color): a line
          means two people have both committed to the same file(s) — more shared files, a thicker line and a
          closer pull — so a tight cluster is a real sub-team, working on the same code. No line among this group
          just means their work doesn't overlap enough to register, not an error. Color is a separate signal —
          each person's primary module, a broader "what area do they mostly work in" label, not what drives the
          clustering. A cluster can span several colors; someone whose neighbors are mixed colors works across
          boundaries.
        </p>
        {topology.loading && <LoadingRows rows={8} height={40} />}
        {topology.error && <ErrorState error={topology.error} onRetry={topology.reload} />}
        {topology.data && topology.data.nodes.length === 0 && (
          <EmptyState title="Not enough activity to map" subtitle="Track a repo with more contributor history." />
        )}
        {topology.data && topology.data.nodes.length > 0 && (
          <>
            <GraphView
              nodes={topology.data.nodes}
              edges={topology.data.edges}
              height={560}
              colorForNode={topologyColor}
              hrefForNode={topologyHref}
              spacingScale={1.7}
            />
            <GraphLegend
              items={[{ color: ["var(--cat-1)", "var(--cat-3)", "var(--cat-5)"], label: "colored by primary module" }]}
            />
          </>
        )}
      </div>

      <div className="page-header">
        <h2 className="page-title" style={{ fontSize: 17 }}>
          Collaboration path
        </h2>
        <p className="page-subtitle">
          Find the shortest chain of shared files connecting two authors — a direct shared file, or one shared
          bridge author, resolved as a directed graph traversal anchored on the two people you pick.
        </p>
      </div>

      <div className="card card-pad">
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-end" }}>
          <AuthorPicker label="From" value={a} onChange={setA} />
          <div style={{ fontSize: 18, color: "var(--text-muted)", paddingBottom: 10 }}>→</div>
          <AuthorPicker label="To" value={b} onChange={setB} />
        </div>

        {a && b && (
          <div style={{ marginTop: 24 }}>
            {path.loading && <LoadingRows rows={3} />}
            {path.error && <ErrorState error={path.error} onRetry={path.reload} />}
            {path.data && !path.data.found && (
              <EmptyState title="No connection found" subtitle="These two authors share no traceable path through commits and files." />
            )}
            {path.data?.found && (
              <div>
                <div style={{ fontSize: 12.5, color: "var(--text-muted)", marginBottom: 10 }}>
                  {path.data.hops} hop{path.data.hops === 1 ? "" : "s"} apart
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
                  {path.data.steps.map((s, i) => (
                    <span key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {s.kind === "File" ? (
                        <Link to={fileHref(s.id)} className="badge">
                          {s.label}
                        </Link>
                      ) : (
                        <span className="badge" style={{ borderColor: "var(--cat-1)", color: "var(--cat-1)" }}>
                          {s.kind === "Author" ? s.label : s.label.slice(0, 40)}
                        </span>
                      )}
                      {i < path.data!.steps.length - 1 && <span style={{ color: "var(--text-muted)" }}>→</span>}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        {(!a || !b) && (
          <div style={{ marginTop: 20 }}>
            <EmptyState title="Pick two authors" subtitle="Search and select an author on each side to trace a path between them." />
          </div>
        )}
      </div>
    </div>
  );
}
