import { useCallback } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";

const QUESTIONS = [
  {
    q: "If I touch this file, what tends to break with it?",
    a: "Logical coupling mined straight from the commit log — files that keep showing up in the same commits, ranked and traversable two hops out.",
    to: "/dashboard",
    cta: "See today's hotspots",
  },
  {
    q: "Who actually owns this part of the codebase?",
    a: "Not the CODEOWNERS file — real ownership, derived from who has actually been committing to each module.",
    to: "/modules",
    cta: "Browse modules",
  },
  {
    q: "How are these two contributors connected?",
    a: "Shortest path between two authors through however many shared files and commits it takes to link them.",
    to: "/collaboration",
    cta: "Trace a path",
  },
  {
    q: "Where does this function, file or author show up?",
    a: "One search box across every file, author and commit in the graph.",
    to: "/search",
    cta: "Try a search",
  },
  {
    q: "If I change this file, what else is likely to break?",
    a: "Blast radius traces coupling one and two hops out from any file — the files that historically change alongside it, ranked by how often.",
    to: "/files",
    cta: "Browse files",
  },
  {
    q: "Who's the single point of failure on this team?",
    a: "Bus-factor-1 files — code only one person has ever committed to — surfaced per author and ranked by how long it's been since they last touched it.",
    to: "/authors",
    cta: "See who's at risk",
  },
];

// Hand-placed, not force-simulated -- this is a fixed illustration of what
// the real (interactive, draggable) GraphView produces, e.g. for a file's
// blast radius. Using a live graph here would tie the landing page to
// whatever repo happens to be tracked; a fixed sample stays meaningful
// and legible regardless of instance state.
const PREVIEW_NODES: { id: string; label: string; hop: 0 | 1 | 2; x: number; y: number }[] = [
  { id: "root", label: "payments/charge.ts", hop: 0, x: 320, y: 190 },
  { id: "h1a", label: "payments/webhook.ts", hop: 1, x: 216, y: 130 },
  { id: "h1b", label: "billing/invoice.ts", hop: 1, x: 442, y: 146 },
  { id: "h1c", label: "payments/refund.ts", hop: 1, x: 298, y: 313 },
  { id: "h2a", label: "notifications/email.ts", hop: 2, x: 122, y: 114 },
  { id: "h2b", label: "queue/worker.ts", hop: 2, x: 200, y: 36 },
  { id: "h2c", label: "ledger/entry.ts", hop: 2, x: 540, y: 163 },
  { id: "h2d", label: "api/routes.ts", hop: 2, x: 487, y: 68 },
  { id: "h2e", label: "tests/payments.test.ts", hop: 2, x: 247, y: 374 },
];

const PREVIEW_EDGES: [string, string][] = [
  ["root", "h1a"],
  ["root", "h1b"],
  ["root", "h1c"],
  ["h1a", "h2a"],
  ["h1a", "h2b"],
  ["h1b", "h2c"],
  ["h1b", "h2d"],
  ["h1c", "h2e"],
];

const PREVIEW_HOP_COLOR: Record<0 | 1 | 2, string> = {
  0: "var(--seq-600)",
  1: "var(--seq-450)",
  2: "var(--seq-300)",
};
const PREVIEW_HOP_RADIUS: Record<0 | 1 | 2, number> = { 0: 16, 1: 10, 2: 7 };

function GraphPreview() {
  const byId = new Map(PREVIEW_NODES.map((n) => [n.id, n]));
  return (
    <svg viewBox="0 0 640 410" style={{ width: "100%", height: "auto", display: "block" }}>
      {PREVIEW_EDGES.map(([a, b]) => {
        const s = byId.get(a)!;
        const t = byId.get(b)!;
        return <line key={`${a}-${b}`} x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke="var(--gridline)" strokeWidth={1.5} />;
      })}
      {PREVIEW_NODES.map((n) => (
        <g key={n.id} transform={`translate(${n.x},${n.y})`}>
          <circle r={PREVIEW_HOP_RADIUS[n.hop]} fill={PREVIEW_HOP_COLOR[n.hop]} stroke="var(--surface-card)" strokeWidth={2} />
          <text
            x={0}
            y={PREVIEW_HOP_RADIUS[n.hop] + 15}
            textAnchor="middle"
            fontSize={10.5}
            fontFamily="var(--font-mono)"
            fill={n.hop === 0 ? "var(--text-primary)" : "var(--text-secondary)"}
            fontWeight={n.hop === 0 ? 600 : 400}
          >
            {n.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

const ENGINEERING_NOTES = [
  {
    title: "Identity, not aliases",
    body: "Reads mailmap-resolved author name/email from git, so a contributor who committed under three different emails shows up as one Author node — not three half-credited strangers.",
  },
  {
    title: "History survives renames",
    body: "File moves and renames are tracked as lineage edges, so coupling, ownership and hotspot scores roll forward instead of resetting to zero the moment a path changes.",
  },
  {
    title: "Instant on load",
    body: "Hotspots, author stats and module coupling are precomputed at ingest time and written onto the graph, not recomputed live on every page view.",
  },
  {
    title: "Safe to point at the internet",
    body: "Ingest is rate-limited per IP with a global cooldown between clones, so a public instance can't be turned into a repo-cloning denial-of-service vector.",
  },
];

const NODES = [
  { label: "Author", cat: "--cat-5" },
  { label: "Commit", cat: "--cat-1" },
  { label: "File", cat: "--cat-3" },
  { label: "Module", cat: "--cat-4" },
];

const RELS = ["AUTHORED", "MODIFIED", "BELONGS_TO"];

export function Home() {
  const stats = useApi(useCallback(() => api.stats(), []));
  const hasData = !!stats.data && stats.data.file_count > 0;

  return (
    <div
      style={{
        minHeight: "100vh",
        background: `radial-gradient(1100px 620px at 50% -8%, color-mix(in srgb, var(--cat-1) 24%, transparent), transparent 65%),
          radial-gradient(900px 500px at 88% 18%, color-mix(in srgb, var(--cat-1) 12%, transparent), transparent 60%),
          var(--surface-page)`,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          maxWidth: 1040,
          margin: "0 auto",
          padding: "24px 24px 0",
        }}
      >
        <div style={{ fontWeight: 700, fontSize: 20, letterSpacing: "-0.01em" }}>GitGraph</div>
        <Link
          to={hasData ? "/dashboard" : "/track"}
          className="btn"
          style={{ textDecoration: "none", fontSize: 12.5 }}
        >
          {hasData ? "Open dashboard" : "Track a repo"}
        </Link>
      </header>

      <section
        style={{
          maxWidth: 720,
          margin: "0 auto",
          padding: "9vh 24px 0",
          textAlign: "center",
        }}
      >
        <div
          style={{
            display: "inline-block",
            fontSize: 11.5,
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--cat-1)",
            marginBottom: 16,
          }}
        >
          Git history, modeled as a graph
        </div>
        <h1
          style={{
            fontSize: "clamp(30px, 4.5vw, 44px)",
            lineHeight: 1.12,
            letterSpacing: "-0.02em",
            fontWeight: 700,
            margin: "0 0 18px",
          }}
        >
          See what your codebase's history actually says about it.
        </h1>
        <p
          style={{
            fontSize: 15.5,
            lineHeight: 1.6,
            color: "var(--text-secondary)",
            margin: "0 auto 32px",
            maxWidth: "56ch",
          }}
        >
          Point GitGraph at any public repository. It clones it, mines every commit with{" "}
          <code>git log --numstat</code>, and loads authors, files and modules into a graph you can traverse — coupling,
          hotspots and ownership a file tree can't show you.
        </p>
        <div style={{ display: "flex", gap: 16, alignItems: "center", justifyContent: "center", flexWrap: "wrap" }}>
          <Link
            to={hasData ? "/dashboard" : "/track"}
            className="btn btn-primary"
            style={{ textDecoration: "none", fontSize: 14, padding: "11px 22px" }}
          >
            {hasData ? "Explore the live demo →" : "Track a repository →"}
          </Link>
          {hasData && (
            <Link to="/track" style={{ fontSize: 13.5, color: "var(--text-secondary)", textDecoration: "none" }}>
              or paste your own repo link →
            </Link>
          )}
        </div>
      </section>

      <section style={{ maxWidth: 900, margin: "64px auto 0", padding: "0 24px" }}>
        <div className="card card-pad" style={{ background: "var(--surface-raised)" }}>
          <GraphPreview />
        </div>
        <div style={{ display: "flex", justifyContent: "center", gap: 22, flexWrap: "wrap", marginTop: 14 }}>
          <Legend color="var(--seq-600)" text="the file you're touching" />
          <Legend color="var(--seq-450)" text="changes with it directly" />
          <Legend color="var(--seq-300)" text="two hops out" />
        </div>
        <p style={{ textAlign: "center", fontSize: 12.5, color: "var(--text-muted)", margin: "10px auto 0", maxWidth: "52ch" }}>
          A blast radius, as GitGraph draws it — every graph in the app is this same interactive view (drag nodes,
          scroll to zoom, click through) over different node types.
        </p>
      </section>

      {hasData && stats.data && (
        <section style={{ maxWidth: 720, margin: "56px auto 0", padding: "0 24px" }}>
          <div style={{ fontSize: 11.5, color: "var(--text-muted)", textAlign: "center", marginBottom: 14 }}>
            Right now, this instance has mined
          </div>
          <div className="grid grid-stats">
            <MiniStat label="Files" value={stats.data.file_count} />
            <MiniStat label="Commits" value={stats.data.commit_count} />
            <MiniStat label="Authors" value={stats.data.author_count} />
            <MiniStat label="Modules" value={stats.data.module_count} />
          </div>
        </section>
      )}

      <section style={{ maxWidth: 1040, margin: "96px auto 0", padding: "0 24px" }}>
        <h2
          style={{
            textAlign: "center",
            fontSize: 12.5,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: "var(--text-muted)",
            margin: "0 0 28px",
          }}
        >
          Questions a file tree can't answer
        </h2>
        <div className="grid grid-2">
          {QUESTIONS.map((item) => (
            <Link
              key={item.q}
              to={item.to}
              className="card card-pad"
              style={{ textDecoration: "none", color: "inherit", display: "block" }}
            >
              <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8, letterSpacing: "-0.005em" }}>
                {item.q}
              </div>
              <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.55, marginBottom: 12 }}>
                {item.a}
              </div>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--cat-1)" }}>{item.cta} →</div>
            </Link>
          ))}
        </div>
      </section>

      <section style={{ maxWidth: 1040, margin: "96px auto 0", padding: "0 24px" }}>
        <h2
          style={{
            textAlign: "center",
            fontSize: 12.5,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: "var(--text-muted)",
            margin: "0 0 28px",
          }}
        >
          Four node types, three relationships — that's the whole schema
        </h2>
        <div
          className="card card-pad"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexWrap: "wrap",
            gap: 4,
            padding: "28px 20px",
          }}
        >
          {NODES.map((node, i) => (
            <div key={node.label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  padding: "7px 14px",
                  borderRadius: 999,
                  border: `1px solid var(${node.cat})`,
                  color: `var(${node.cat})`,
                  background: `color-mix(in srgb, var(${node.cat}) 10%, transparent)`,
                }}
              >
                {node.label}
              </span>
              {i < RELS.length && (
                <span
                  className="mono"
                  style={{
                    fontSize: 10.5,
                    color: "var(--text-muted)",
                    padding: "0 8px",
                    whiteSpace: "nowrap",
                  }}
                >
                  — {RELS[i]} →
                </span>
              )}
            </div>
          ))}
        </div>
        <p style={{ textAlign: "center", fontSize: 12.5, color: "var(--text-muted)", margin: "16px auto 0", maxWidth: "60ch" }}>
          Deliberately minimal — all of it derivable from <code>git log --numstat</code>, no synthetic data. The
          richness comes from traversal, not the schema.
        </p>
      </section>

      <section style={{ maxWidth: 1040, margin: "96px auto 0", padding: "0 24px" }}>
        <h2
          style={{
            textAlign: "center",
            fontSize: 12.5,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: "var(--text-muted)",
            margin: "0 0 28px",
          }}
        >
          Built for accuracy, not vanity metrics
        </h2>
        <div>
          {ENGINEERING_NOTES.map((note, i) => (
            <div
              key={note.title}
              style={{
                display: "flex",
                gap: 24,
                alignItems: "baseline",
                flexWrap: "wrap",
                padding: "20px 0",
                borderTop: i === 0 ? "none" : "1px solid var(--gridline)",
              }}
            >
              <div
                className="mono"
                style={{ fontSize: 12.5, color: "var(--cat-1)", fontWeight: 700, flex: "none", width: 26 }}
              >
                {String(i + 1).padStart(2, "0")}
              </div>
              <div style={{ fontSize: 14.5, fontWeight: 600, letterSpacing: "-0.005em", flex: "1 1 200px", minWidth: 160 }}>
                {note.title}
              </div>
              <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.55, flex: "3 1 380px" }}>
                {note.body}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section style={{ maxWidth: 720, margin: "96px auto 0", padding: "0 24px 120px", textAlign: "center" }}>
        <Link
          to={hasData ? "/dashboard" : "/track"}
          className="btn btn-primary"
          style={{ textDecoration: "none", fontSize: 14, padding: "11px 24px" }}
        >
          {hasData ? "Try it yourself →" : "Track your first repository →"}
        </Link>
      </section>
    </div>
  );
}

function Legend({ color, text }: { color: string; text: string }) {
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12, color: "var(--text-secondary)" }}>
      <span style={{ width: 9, height: 9, borderRadius: "50%", background: color, flex: "none" }} />
      {text}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="card card-pad" style={{ textAlign: "center" }}>
      <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.01em", fontVariantNumeric: "tabular-nums" }}>
        {value.toLocaleString()}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4, textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {label}
      </div>
    </div>
  );
}
