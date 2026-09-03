import { useCallback } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { GraphView } from "../components/GraphView";
import { useApi } from "../hooks/useApi";
import type { GraphEdge, GraphNode } from "../api/types";

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
  {
    q: "What would break if I changed this function?",
    a: "A real call graph, parsed from the actual source — not git history. Every caller and callee, each edge marked with how confidently it was resolved.",
    to: "/functions",
    cta: "Explore the call graph",
  },
];

// Fixed sample data, not a tracked repo's real blast radius -- using a live
// graph tied to whatever repo happens to be tracked would make the landing
// page's meaning depend on instance state. This still renders through the
// real, interactive GraphView (force layout, drag, zoom, hover) so what you
// see here is exactly what the app produces, just with `navigable={false}`
// so a stray click can't route to a file that doesn't exist.
const PREVIEW_NODES_BASE: Omit<GraphNode, "sole_owned" | "trending_worse" | "group">[] = [
  { id: "root", kind: "File", label: "charge.ts", subtitle: "payments/charge.ts", hop: 0, weight: 2 },
  { id: "h1a", kind: "File", label: "webhook.ts", subtitle: "payments/webhook.ts", hop: 1, weight: 3 },
  { id: "h1b", kind: "File", label: "invoice.ts", subtitle: "billing/invoice.ts", hop: 1, weight: 1 },
  { id: "h1c", kind: "File", label: "refund.ts", subtitle: "payments/refund.ts", hop: 1, weight: 2 },
  { id: "h2a", kind: "File", label: "email.ts", subtitle: "notifications/email.ts", hop: 2, weight: 1 },
  { id: "h2b", kind: "File", label: "worker.ts", subtitle: "queue/worker.ts", hop: 2, weight: 0 },
  { id: "h2c", kind: "File", label: "entry.ts", subtitle: "ledger/entry.ts", hop: 2, weight: 1 },
  { id: "h2d", kind: "File", label: "routes.ts", subtitle: "api/routes.ts", hop: 2, weight: 0 },
  { id: "h2e", kind: "File", label: "payments.test.ts", subtitle: "tests/payments.test.ts", hop: 2, weight: 1 },
];
const PREVIEW_NODES: GraphNode[] = PREVIEW_NODES_BASE.map((n) => ({
  ...n,
  sole_owned: false,
  trending_worse: false,
  group: "",
}));

const PREVIEW_EDGES: GraphEdge[] = [
  { source: "root", target: "h1a", weight: 6 },
  { source: "root", target: "h1b", weight: 3 },
  { source: "root", target: "h1c", weight: 4 },
  { source: "h1a", target: "h2a", weight: 2 },
  { source: "h1a", target: "h2b", weight: 1 },
  { source: "h1b", target: "h2c", weight: 2 },
  { source: "h1b", target: "h2d", weight: 1 },
  { source: "h1c", target: "h2e", weight: 2 },
];

// Same "fixed sample, real component" idiom as PREVIEW_NODES/EDGES above --
// this one shows the *other* graph: parsed from source, not git history, so
// it needs its own directed sample rather than reusing the file-coupling
// one. One low-confidence edge included on purpose, so the dashed styling
// (a best-effort name match, not a same-file/type-checked resolution) is
// visible on the landing page, not just discovered later inside the app.
const PREVIEW_FN_NODES_BASE: Omit<GraphNode, "sole_owned" | "trending_worse">[] = [
  { id: "fn-root", kind: "Function", label: "chargeCard", subtitle: "payments/charge.ts - chargeCard", hop: 0, weight: 2, group: "" },
  { id: "fn-c1", kind: "Function", label: "submit", subtitle: "checkout/flow.ts - CheckoutFlow.submit", hop: 1, weight: 1, group: "" },
  { id: "fn-c2", kind: "Function", label: "process", subtitle: "queue/retry.ts - RetryQueue.process", hop: 1, weight: 1, group: "" },
  { id: "fn-e1", kind: "Function", label: "validateCard", subtitle: "payments/validate.ts - validateCard", hop: 1, weight: 1, group: "" },
  { id: "fn-e2", kind: "Function", label: "send", subtitle: "payments/gateway.ts - Gateway.send", hop: 1, weight: 2, group: "" },
  { id: "fn-e3", kind: "Function", label: "logTransaction", subtitle: "ledger/log.ts - logTransaction", hop: 1, weight: 1, group: "" },
  { id: "fn-h2a", kind: "Function", label: "onCharge", subtitle: "webhooks/handlers.ts - onCharge", hop: 2, weight: 1, group: "" },
];
const PREVIEW_FN_NODES: GraphNode[] = PREVIEW_FN_NODES_BASE.map((n) => ({ ...n, sole_owned: false, trending_worse: false }));

const PREVIEW_FN_EDGES: GraphEdge[] = [
  { source: "fn-c1", target: "fn-root", weight: 5, confidence: "high" },
  { source: "fn-c2", target: "fn-root", weight: 2, confidence: "high" },
  { source: "fn-root", target: "fn-e1", weight: 4, confidence: "high" },
  { source: "fn-root", target: "fn-e2", weight: 6, confidence: "high" },
  { source: "fn-root", target: "fn-e3", weight: 1, confidence: "low" },
  { source: "fn-e2", target: "fn-h2a", weight: 2, confidence: "high" },
];

function fnEdgeStyle(e: { confidence?: string }): { dash?: string } {
  return { dash: e.confidence === "low" ? "4 3" : undefined };
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
  {
    title: "Confidence, not certainty",
    body: "Every call-graph edge is tagged with how it was resolved — same-file, type-checked, import-resolved, or a best-effort name match. An uncertain guess is shown as uncertain, never quietly presented as fact.",
  },
];

const NODES = [
  { label: "Author", cat: "--cat-5" },
  { label: "Commit", cat: "--cat-1" },
  { label: "File", cat: "--cat-3" },
  { label: "Module", cat: "--cat-4" },
];

const RELS = ["AUTHORED", "MODIFIED", "BELONGS_TO"];

// A second, separate schema -- parsed from source at ingest time, not
// derived from commits. Kept as its own graph rather than merged into
// NODES/RELS above: a statistical signal (files that change together) and
// a structural one (functions that call each other) answer different
// questions, and blurring them into one schema would make neither honest.
const FN_NODES = [
  { label: "File", cat: "--cat-3" },
  { label: "Function", cat: "--cat-1" },
];

const FN_RELS = ["DEFINED_IN", "CALLS", "IMPORTS"];

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
          Git history and code structure, modeled as a graph
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
          hotspots and ownership a file tree can't show you. Then it goes one level deeper: parsing the actual source
          to build a real function-level call graph, so you can see not just which files change together, but which
          functions actually depend on each other.
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

      <section style={{ maxWidth: 1040, margin: "64px auto 0", padding: "0 24px" }}>
        <GraphView nodes={PREVIEW_NODES} edges={PREVIEW_EDGES} navigable={false} height={560} />
        <p style={{ textAlign: "center", fontSize: 12.5, color: "var(--text-muted)", margin: "14px auto 0", maxWidth: "52ch" }}>
          A blast radius, live — color shows hop distance from the selected file (see the legend below the graph),
          and a line means two files were touched in the same commit. Drag nodes, scroll to zoom. This is sample
          data; every graph in the real app is this same interactive view over your own repo's history.
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
          A function level dependency graph, parsed straight from the code
        </h2>
        <GraphView
          nodes={PREVIEW_FN_NODES}
          edges={PREVIEW_FN_EDGES}
          navigable={false}
          height={480}
          directed
          edgeStyleForLink={fnEdgeStyle}
        />
        <p style={{ textAlign: "center", fontSize: 12.5, color: "var(--text-muted)", margin: "14px auto 0", maxWidth: "56ch" }}>
          Not git history — real static analysis, using the actual TypeScript compiler and Python's own parser.
          Arrows show which function calls which; the dashed edge is a best-effort name match rather than a
          verified resolution, shown as uncertain instead of pretending every guess is a fact. This is sample data;
          the real thing is built from your repo's actual functions.
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
          Two graphs, kept deliberately separate
        </h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SchemaRow eyebrow="From git history" nodes={NODES} rels={RELS} />
          <SchemaRow eyebrow="From parsing the source" nodes={FN_NODES} rels={FN_RELS} />
        </div>
        <p style={{ textAlign: "center", fontSize: 12.5, color: "var(--text-muted)", margin: "16px auto 0", maxWidth: "60ch" }}>
          One is a statistical signal — files that tend to change together, derived from <code>git log --numstat</code>.
          The other is structural — functions that actually call each other, derived from parsing the code itself.
          Deliberately never merged into one graph: they answer different questions, and blurring them would make
          neither honest.
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

function SchemaRow({ eyebrow, nodes, rels }: { eyebrow: string; nodes: { label: string; cat: string }[]; rels: string[] }) {
  return (
    <div className="card card-pad" style={{ padding: "22px 20px" }}>
      <div
        className="mono"
        style={{ fontSize: 10.5, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 14 }}
      >
        {eyebrow}
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", flexWrap: "wrap", gap: 4 }}>
        {nodes.map((node, i) => (
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
            {i < rels.length && (
              <span
                className="mono"
                style={{ fontSize: 10.5, color: "var(--text-muted)", padding: "0 8px", whiteSpace: "nowrap" }}
              >
                — {rels[i]} →
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
