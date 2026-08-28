import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { useNavigate } from "react-router-dom";
import { authorHref, fileHref } from "../api/client";
import type { GraphEdge as ApiEdge, GraphNode as ApiNode } from "../api/types";

interface SimNode extends SimulationNodeDatum, ApiNode {}
interface SimLink extends SimulationLinkDatum<SimNode> {
  weight: number;
}

// Mind-map look: vivid flat bubbles per hop tier with labels set inside the
// bubble instead of below it. The canvas itself is always transparent, so
// it blends into whatever card/page it's placed on rather than showing its
// own background.
const HOP_COLOR: Record<number, string> = { 0: "#f2c14e", 1: "var(--cat-1)", 2: "#238636" };
const HOP_TEXT_ON_FILL = "#16202f";
const HOP_LABEL: Record<number, string> = { 0: "selected", 1: "direct", 2: "2nd-degree" };
const HOP_RADIUS: Record<number, number> = { 0: 42, 1: 26, 2: 18 };
const HOP_FONT_SIZE: Record<number, number> = { 0: 14, 1: 12, 2: 10.5 };
const HINT_COLOR = "var(--text-muted)";
const CHAR_WIDTH_EM = 0.56;
const LINE_HEIGHT_EM = 1.2;
const PROXIMITY_RADIUS = 100;
const PROXIMITY_PUSH = 11;

function weightRadius(n: SimNode): number {
  return (HOP_RADIUS[n.hop] ?? 18) + Math.min(20, (n.weight ?? 0) * 2.2);
}

// Deterministic 0..1 pseudo-random from a string -- used to give each edge
// its own stable "personality" (curve direction/amount, branch length) so a
// hub-and-spoke graph reads as an organic, irregular network instead of a
// perfectly symmetric spiral/pinwheel.
function hash01(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
  return ((h >>> 0) % 10000) / 10000;
}

// Curves from source to target, then trims each end back along the curve's
// local direction (toward the control point) by that node's own radius, so
// the drawn line stops right at the bubble's edge instead of running under
// it to the center (visible wherever a bubble is hollow or semi-transparent).
// curveFactor varies per edge (sign and magnitude) so spokes off the same
// hub don't all bow the same way, which is what reads as a spiral.
function curvedPath(sx: number, sy: number, tx: number, ty: number, sr: number, tr: number, curveFactor: number): string {
  const dx = tx - sx;
  const dy = ty - sy;
  const dist = Math.hypot(dx, dy) || 1;
  const offset = dist * curveFactor;
  const mx = (sx + tx) / 2 + (-dy / dist) * offset;
  const my = (sy + ty) / 2 + (dx / dist) * offset;

  const sToC = Math.hypot(mx - sx, my - sy) || 1;
  const startX = sx + ((mx - sx) / sToC) * sr;
  const startY = sy + ((my - sy) / sToC) * sr;

  const tToC = Math.hypot(mx - tx, my - ty) || 1;
  const endX = tx + ((mx - tx) / tToC) * tr;
  const endY = ty + ((my - ty) / tToC) * tr;

  return `M ${startX} ${startY} Q ${mx} ${my} ${endX} ${endY}`;
}

// Breaks a label into lines at natural boundaries (space/./-/_) only --
// never mid-word. Greedily packs words onto a line up to maxChars; a single
// word longer than maxChars gets its own (wider) line rather than being cut.
function packLabelLines(label: string, maxChars: number): string[] {
  const tokens = label.split(/(?<=[-_. ])/).filter(Boolean);
  const lines: string[] = [];
  let current = "";
  for (const token of tokens) {
    if (current === "" || (current + token).length <= maxChars) {
      current += token;
    } else {
      lines.push(current.trim());
      current = token;
    }
  }
  if (current) lines.push(current.trim());
  return lines;
}

// Lays out a label for a bubble whose radius is only a lower bound (driven
// by weight/hop): wraps at that bubble's natural width, then grows the
// radius to whatever the wrapped text actually needs so nothing is cut off.
function layoutLabel(label: string, minRadius: number, fontSize: number): { lines: string[]; radius: number } {
  const charW = fontSize * CHAR_WIDTH_EM;
  const lineH = fontSize * LINE_HEIGHT_EM;
  const wrapChars = Math.max(4, Math.floor((minRadius * 1.7) / charW));
  const lines = packLabelLines(label, wrapChars);
  const longestLine = Math.max(...lines.map((l) => l.length));
  const radiusForWidth = (longestLine * charW) / 2 + 10;
  const radiusForHeight = (lines.length * lineH) / 2 + 8;
  const radius = Math.max(minRadius, radiusForWidth, radiusForHeight);
  return { lines, radius };
}

// Assigns each node a "home" angle around the hub: hop-1 nodes get evenly
// spaced slots (so branches don't fight over territory), and each hop-2
// node's angle is nudged toward its own parent's slot, spread out among its
// siblings within a fraction of that slot's width. Combined with a gentle
// forceX/forceY pull toward these angles, this keeps whole branches from
// tangling into each other -- crossings still happen locally (an edge can
// still cross a nearby one), but not across the whole graph.
function computeAngles(nodeCopies: SimNode[], linkCopies: SimLink[]): Map<string, number> {
  const angles = new Map<string, number>();
  const hop1 = nodeCopies.filter((n) => n.hop === 1).sort((a, b) => (a.id < b.id ? -1 : 1));
  const slot = (2 * Math.PI) / Math.max(1, hop1.length);
  hop1.forEach((n, i) => angles.set(n.id, i * slot - Math.PI / 2));

  const childrenOf = new Map<string, string[]>();
  for (const l of linkCopies) {
    const s = typeof l.source === "object" ? (l.source as SimNode).id : (l.source as unknown as string);
    const t = typeof l.target === "object" ? (l.target as SimNode).id : (l.target as unknown as string);
    if (!angles.has(s)) continue;
    if (!childrenOf.has(s)) childrenOf.set(s, []);
    childrenOf.get(s)!.push(t);
  }
  for (const [parentId, kids] of childrenOf) {
    const parentAngle = angles.get(parentId)!;
    const spread = slot * 0.8;
    const sortedKids = [...kids].sort();
    sortedKids.forEach((childId, i) => {
      if (angles.has(childId)) return;
      const offset = sortedKids.length > 1 ? (i / (sortedKids.length - 1) - 0.5) * spread : 0;
      angles.set(childId, parentAngle + offset);
    });
  }
  return angles;
}

// Centers and scales the settled layout so every bubble fits in the
// viewport, instead of always resetting to identity (which clips whenever
// the graph's natural size -- driven by label length and node count --
// exceeds the container).
function fitView(nodeCopies: SimNode[], width: number, height: number): { x: number; y: number; scale: number } {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const n of nodeCopies) {
    const rad = layoutLabel(n.label, weightRadius(n), HOP_FONT_SIZE[n.hop] ?? 10.5).radius;
    const x = n.x ?? 0;
    const y = n.y ?? 0;
    minX = Math.min(minX, x - rad);
    maxX = Math.max(maxX, x + rad);
    minY = Math.min(minY, y - rad);
    maxY = Math.max(maxY, y + rad);
  }
  if (!Number.isFinite(minX)) return { x: 0, y: 0, scale: 1 };
  const pad = 24;
  const bboxW = Math.max(1, maxX - minX);
  const bboxH = Math.max(1, maxY - minY);
  // No lower floor beyond a sanity minimum: a graph fully visible but small
  // beats one that's clipped by the container. This used to floor at 0.3,
  // which clipped sprawling layouts (e.g. spacingScale pushing unconnected
  // nodes far out under charge repulsion with nothing pulling them back) --
  // "whole graph visible on load" always wins over a minimum zoom level;
  // scroll-to-zoom is already how you get closer after that.
  const scale = Math.min(1.4, Math.max(0.06, Math.min((width - pad * 2) / bboxW, (height - pad * 2) / bboxH)));
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  return { x: width / 2 - cx * scale, y: height / 2 - cy * scale, scale };
}

export function GraphView({
  nodes,
  edges,
  height = 460,
  navigable = true,
  colorForNode,
  hrefForNode,
  strokeForNode,
  spacingScale = 1,
  clusterSensitivity = 1,
  nearestInTooltip,
}: {
  nodes: ApiNode[];
  edges: ApiEdge[];
  height?: number;
  navigable?: boolean;
  // Overrides today's hop-tier color (File/Author blast-radius & collab
  // views) for graphs with a different node kind (Module, etc). Omit to
  // keep the default hop-tier look untouched.
  colorForNode?: (node: ApiNode) => string;
  // Overrides today's hop!==0 ? fileHref/authorHref : null click behavior.
  // Return null to make a node non-navigable. Omit to keep the default.
  hrefForNode?: (node: ApiNode) => string | null;
  // Multiplies charge repulsion, link distance, and collide padding
  // together. >1 pushes unconnected nodes further apart while strongly-
  // weighted edges still pull their endpoints close (link distance already
  // shrinks with edge weight) -- makes edge-driven clustering read more
  // clearly for graphs where "who's close to whom" is the point, without
  // changing anything for graphs that don't opt in.
  spacingScale?: number;
  // Second, independent color channel for the node's ring (fill still comes
  // from colorForNode/hop-tier) -- e.g. flagging a node as a *different
  // kind* of important without repainting its severity color. Omit to keep
  // the ring the same color as the fill (today's behavior).
  strokeForNode?: (node: ApiNode) => string;
  // How steeply link distance responds to edge weight, independent of
  // spacingScale (which scales everything uniformly, so it can't change how
  // *different* a strong pair looks from a weak one). >1 makes the
  // strongest edges pull their endpoints dramatically closer while weak/no
  // edges stay at the base distance -- for graphs where "how much closer
  // are the real collaborators" is the point, not just "more room overall".
  clusterSensitivity?: number;
  // Opt-in tooltip addition: lists the closest other nodes by settled
  // layout distance (not just direct edges -- position already reflects the
  // whole force layout, so it surfaces nodes pulled close by indirect/
  // transitive overlap too). For team topology this reads as "who's this
  // person's likely sub-team", which a hover tooltip otherwise can't show
  // since edges alone only capture direct file-sharing pairs.
  nearestInTooltip?: { label: string; count?: number };
}) {
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [simLinks, setSimLinks] = useState<SimLink[]>([]);
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  const [settled, setSettled] = useState(false);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null);
  const [pointerLocalPos, setPointerLocalPos] = useState<{ x: number; y: number } | null>(null);
  const dragRef = useRef<{ id: string; pointerId: number } | null>(null);
  const panRef = useRef<{ startX: number; startY: number; origX: number; origY: number; pointerId: number } | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // React's onWheel JSX prop attaches wheel listeners as passive (since
  // React 17, for scroll performance), which silently ignores
  // preventDefault() inside them -- the page scrolls right along with the
  // graph zoom regardless of calling it. Attaching natively with
  // { passive: false } is the only way to actually stop that.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      setView((v) => ({ ...v, scale: Math.min(2.4, Math.max(0.4, v.scale - e.deltaY * 0.001)) }));
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  useEffect(() => {
    if (!width || !height || nodes.length === 0) {
      setSimNodes([]);
      setSimLinks([]);
      return;
    }
    const nodeCopies: SimNode[] = nodes.map((n) => ({ ...n }));
    const byId = new Map(nodeCopies.map((n) => [n.id, n]));
    const linkCopies: SimLink[] = edges
      .filter((e) => byId.has(e.source) && byId.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, weight: e.weight }));

    const linkKey = (l: SimLink) => {
      const s = typeof l.source === "object" ? (l.source as SimNode).id : (l.source as unknown as string);
      const t = typeof l.target === "object" ? (l.target as SimNode).id : (l.target as unknown as string);
      return `${s}|${t}`;
    };

    const angles = computeAngles(nodeCopies, linkCopies);
    const RADIAL_BY_HOP: Record<number, number> = { 0: 0, 1: 190 * spacingScale, 2: 370 * spacingScale };
    const targetX = (n: SimNode) => {
      const a = angles.get(n.id);
      if (a == null) return width / 2;
      return width / 2 + Math.cos(a) * (RADIAL_BY_HOP[n.hop] ?? 370 * spacingScale);
    };
    const targetY = (n: SimNode) => {
      const a = angles.get(n.id);
      if (a == null) return height / 2;
      return height / 2 + Math.sin(a) * (RADIAL_BY_HOP[n.hop] ?? 370 * spacingScale);
    };

    const sim = forceSimulation(nodeCopies)
      .force("charge", forceManyBody().strength(-680 * spacingScale))
      .force(
        "link",
        forceLink<SimNode, SimLink>(linkCopies)
          .id((d) => d.id)
          .distance((l) => {
            // No cap on the reduction itself (unlike before) -- the floor
            // below already prevents it from going negative/absurd, and
            // removing the cap lets clusterSensitivity keep differentiating
            // all the way up to whatever the real max weight in this graph
            // is, instead of every edge above ~11 looking identically close.
            const reduction = (l.weight ?? 1) * 8 * clusterSensitivity;
            const base = 260 - reduction;
            // Jitter shrinks as sensitivity rises so a genuinely tight
            // cluster reads as tight, not noisy -- at high sensitivity the
            // weight signal should dominate, not this per-edge randomness.
            const jitter = (hash01(linkKey(l)) - 0.5) * (110 / Math.max(1, clusterSensitivity));
            return Math.max(40, base + jitter) * spacingScale;
          })
      )
      .force("center", forceCenter(width / 2, height / 2))
      .force(
        "x",
        forceX<SimNode>(targetX).strength((d) => ((d as SimNode).hop === 0 ? 0.35 : 0.1))
      )
      .force(
        "y",
        forceY<SimNode>(targetY).strength((d) => ((d as SimNode).hop === 0 ? 0.35 : 0.1))
      )
      .force(
        "collide",
        forceCollide((d) => {
          const sn = d as SimNode;
          return layoutLabel(sn.label, weightRadius(sn), HOP_FONT_SIZE[sn.hop] ?? 10.5).radius + 22 * spacingScale;
        })
      )
      .stop();

    for (let i = 0; i < 320; i++) sim.tick();
    setSimNodes(nodeCopies);
    setSimLinks(linkCopies);
    setView(fitView(nodeCopies, width, height));
    setHoveredId(null);
    setSettled(false);
  }, [nodes, edges, width, height]);

  useEffect(() => {
    if (simNodes.length === 0) return;
    let raf2 = 0;
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => setSettled(true));
    });
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
    };
  }, [simNodes]);

  const nodeById = useMemo(() => new Map(simNodes.map((n) => [n.id, n])), [simNodes]);

  const radiusById = useMemo(
    () =>
      new Map(
        simNodes.map((n) => [n.id, layoutLabel(n.label, weightRadius(n), HOP_FONT_SIZE[n.hop] ?? 10.5).radius])
      ),
    [simNodes]
  );

  const neighbors = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const l of simLinks) {
      const s = typeof l.source === "object" ? (l.source as SimNode).id : (l.source as unknown as string);
      const t = typeof l.target === "object" ? (l.target as SimNode).id : (l.target as unknown as string);
      if (!m.has(s)) m.set(s, new Set());
      if (!m.has(t)) m.set(t, new Set());
      m.get(s)!.add(t);
      m.get(t)!.add(s);
    }
    return m;
  }, [simLinks]);

  const maxHop = useMemo(() => nodes.reduce((m, n) => Math.max(m, n.hop), 0), [nodes]);

  const nearestById = useMemo(() => {
    const m = new Map<string, SimNode[]>();
    if (!nearestInTooltip) return m;
    const count = nearestInTooltip.count ?? 4;
    const withPos = simNodes.filter((n) => n.x != null && n.y != null);
    for (const n of withPos) {
      const ranked = withPos
        .filter((o) => o.id !== n.id)
        .map((o) => ({ node: o, dist: Math.hypot((o.x ?? 0) - (n.x ?? 0), (o.y ?? 0) - (n.y ?? 0)) }))
        .sort((a, b) => a.dist - b.dist)
        .slice(0, count)
        .map((r) => r.node);
      m.set(n.id, ranked);
    }
    return m;
  }, [simNodes, nearestInTooltip]);

  const updateNodePos = useCallback((id: string, x: number, y: number) => {
    setSimNodes((prev) => prev.map((n) => (n.id === id ? { ...n, x, y, fx: x, fy: y } : n)));
  }, []);

  function toGraphCoords(clientX: number, clientY: number) {
    const rect = containerRef.current!.getBoundingClientRect();
    return { x: (clientX - rect.left - view.x) / view.scale, y: (clientY - rect.top - view.y) / view.scale };
  }

  function onNodePointerDown(e: RPointerEvent, id: string) {
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    dragRef.current = { id, pointerId: e.pointerId };
  }

  function onContainerPointerDown(e: RPointerEvent) {
    (e.target as Element).setPointerCapture(e.pointerId);
    panRef.current = { startX: e.clientX, startY: e.clientY, origX: view.x, origY: view.y, pointerId: e.pointerId };
  }

  function onContainerPointerMove(e: RPointerEvent) {
    setHoverPos(toGraphCoords(e.clientX, e.clientY));
    const rect = containerRef.current!.getBoundingClientRect();
    setPointerLocalPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    if (dragRef.current && dragRef.current.pointerId === e.pointerId) {
      const { x, y } = toGraphCoords(e.clientX, e.clientY);
      updateNodePos(dragRef.current.id, x, y);
      return;
    }
    if (panRef.current && panRef.current.pointerId === e.pointerId) {
      const dx = e.clientX - panRef.current.startX;
      const dy = e.clientY - panRef.current.startY;
      setView((v) => ({ ...v, x: panRef.current!.origX + dx, y: panRef.current!.origY + dy }));
    }
  }

  function onContainerPointerUp() {
    dragRef.current = null;
    panRef.current = null;
  }

  function onContainerPointerLeave() {
    onContainerPointerUp();
    setHoverPos(null);
    setPointerLocalPos(null);
    setHoveredId(null);
  }

  if (!nodes.length) return null;

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        height,
        position: "relative",
        overflow: "hidden",
        borderRadius: "var(--radius-md)",
        background: "transparent",
        touchAction: "none",
        cursor: "grab",
      }}
      onPointerDown={onContainerPointerDown}
      onPointerMove={onContainerPointerMove}
      onPointerUp={onContainerPointerUp}
      onPointerLeave={onContainerPointerLeave}
    >
      <svg width="100%" height={height}>
        <g transform={`translate(${view.x},${view.y}) scale(${view.scale})`}>
          {simLinks.map((l, i) => {
            const s = typeof l.source === "object" ? l.source : nodeById.get(l.source as unknown as string);
            const t = typeof l.target === "object" ? l.target : nodeById.get(l.target as unknown as string);
            if (!s || !t || s.x == null || t.x == null || t.y == null || s.y == null) return null;
            const relevant = !hoveredId || s.id === hoveredId || t.id === hoveredId;
            const edgeColor = colorForNode ? colorForNode(t) : HOP_COLOR[(t as SimNode).hop] ?? HOP_COLOR[2];
            const curveFactor = (hash01(`${s.id}|${t.id}`) - 0.5) * 0.46;
            const baseOpacity = Math.min(0.55, 0.18 + Math.min(1, (l.weight ?? 1) / 6) * 0.3);
            const opacity = !settled ? 0 : hoveredId ? (relevant ? Math.min(0.9, baseOpacity + 0.35) : 0.06) : baseOpacity;
            return (
              <path
                key={i}
                d={curvedPath(s.x, s.y, t.x, t.y, radiusById.get(s.id) ?? 0, radiusById.get(t.id) ?? 0, curveFactor)}
                fill="none"
                stroke={edgeColor}
                strokeWidth={Math.max(1, Math.min(3.2, l.weight))}
                style={{ opacity, transition: "opacity 0.35s ease" }}
              />
            );
          })}
          {simNodes.map((n) => {
            const isHub = n.hop === 0;
            const isHovered = n.id === hoveredId;
            const isNeighborOfHover = hoveredId != null && neighbors.get(hoveredId)?.has(n.id);
            const isDimmed = hoveredId != null && !isHovered && !isNeighborOfHover;
            const delay = (n.hop ?? 0) * 90;
            const fontSize = HOP_FONT_SIZE[n.hop] ?? 10.5;
            const { lines, radius: r } = layoutLabel(n.label, weightRadius(n), fontSize);
            const color = colorForNode ? colorForNode(n) : HOP_COLOR[n.hop] ?? HOP_COLOR[2];
            const href = hrefForNode ? hrefForNode(n) : n.hop !== 0 ? (n.kind === "Author" ? authorHref(n.id) : fileHref(n.id)) : null;
            const ringColor = strokeForNode ? strokeForNode(n) : color;

            let pushX = 0;
            let pushY = 0;
            if (hoverPos && dragRef.current?.id !== n.id) {
              const dx = (n.x ?? 0) - hoverPos.x;
              const dy = (n.y ?? 0) - hoverPos.y;
              const dist = Math.hypot(dx, dy);
              const influence = Math.max(0, PROXIMITY_RADIUS - dist) / PROXIMITY_RADIUS;
              if (influence > 0) {
                const eased = influence * influence;
                const push = (eased * PROXIMITY_PUSH) / (dist || 1);
                pushX = dx * push;
                pushY = dy * push;
              }
            }

            return (
              <g
                key={n.id}
                transform={`translate(${n.x ?? 0},${n.y ?? 0})`}
                onPointerDown={(e) => onNodePointerDown(e, n.id)}
                onPointerEnter={() => setHoveredId(n.id)}
                onPointerLeave={() => setHoveredId((cur) => (cur === n.id ? null : cur))}
                onClick={(e) => {
                  e.stopPropagation();
                  if (navigable && href) navigate(href);
                }}
                style={{ cursor: navigable && href ? "pointer" : "default" }}
              >
                <g
                  style={{
                    transform: `translate(${pushX}px, ${pushY}px) scale(${isHovered ? 1.12 : 1})`,
                    transformBox: "fill-box",
                    transformOrigin: "center",
                    transition: "transform 0.15s ease-out",
                  }}
                >
                  <g
                    style={{
                      opacity: !settled ? 0 : isDimmed ? 0.25 : 1,
                      transform: settled ? "scale(1)" : "scale(0.35)",
                    transformBox: "fill-box",
                    transformOrigin: "center",
                    transition: `opacity 0.35s ease ${delay}ms, transform 0.45s cubic-bezier(0.22,1,0.36,1) ${delay}ms`,
                  }}
                >
                  <circle
                    r={r}
                    fill={isHub ? "transparent" : color}
                    stroke={ringColor}
                    strokeWidth={isHub ? 2.5 : strokeForNode ? 3 : 1.5}
                  />
                  <text
                    x={0}
                    y={0}
                    textAnchor="middle"
                    dominantBaseline="central"
                    fontSize={fontSize}
                    fontWeight={isHub ? 700 : 600}
                    fontFamily="var(--font-ui)"
                    fill={isHub ? color : HOP_TEXT_ON_FILL}
                  >
                    {lines.length === 1
                      ? lines[0]
                      : lines.map((line, li) => (
                          <tspan key={li} x={0} dy={li === 0 ? `${-((lines.length - 1) * LINE_HEIGHT_EM) / 2}em` : `${LINE_HEIGHT_EM}em`}>
                            {line}
                          </tspan>
                        ))}
                  </text>
                  </g>
                </g>
              </g>
            );
          })}
        </g>
      </svg>
      {hoveredId &&
        pointerLocalPos &&
        (() => {
          const n = nodeById.get(hoveredId);
          if (!n) return null;
          const text = n.subtitle || n.label;
          const nearest = nearestInTooltip ? nearestById.get(hoveredId) ?? [] : [];
          const tooltipWidth = 260;
          const flipX = pointerLocalPos.x + 18 + tooltipWidth > width;
          const flipY = pointerLocalPos.y + 46 > height;
          return (
            <div
              style={{
                position: "absolute",
                left: flipX ? pointerLocalPos.x - tooltipWidth - 14 : pointerLocalPos.x + 18,
                top: flipY ? pointerLocalPos.y - 34 : pointerLocalPos.y + 18,
                maxWidth: tooltipWidth,
                padding: "6px 10px",
                borderRadius: "var(--radius-sm)",
                background: "var(--surface-raised)",
                border: "1px solid var(--border-strong)",
                boxShadow: "var(--shadow-card)",
                color: "var(--text-primary)",
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                lineHeight: 1.4,
                overflowWrap: "break-word",
                pointerEvents: "none",
                zIndex: 5,
              }}
            >
              {text}
              {nearest.length > 0 && (
                <div style={{ marginTop: 5, paddingTop: 5, borderTop: "1px solid var(--border)" }}>
                  <div style={{ color: "var(--text-muted)", fontSize: 10.5, marginBottom: 2 }}>
                    {nearestInTooltip!.label}
                  </div>
                  {nearest.map((o) => o.label).join(", ")}
                </div>
              )}
            </div>
          );
        })()}
      {!colorForNode && (
        <div
          style={{
            position: "absolute",
            bottom: 10,
            left: 12,
            display: "flex",
            gap: 12,
            fontSize: 11,
            fontFamily: "var(--font-ui)",
            color: HINT_COLOR,
          }}
        >
          {Array.from({ length: Math.min(maxHop, 2) + 1 }, (_, hop) => (
            <span key={hop} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: HOP_COLOR[hop] ?? HOP_COLOR[2],
                  flex: "none",
                }}
              />
              {HOP_LABEL[hop] ?? HOP_LABEL[2]}
            </span>
          ))}
        </div>
      )}
      <div style={{ position: "absolute", bottom: 10, right: 12, fontSize: 11, fontFamily: "var(--font-ui)", color: HINT_COLOR }}>
        drag to arrange · scroll to zoom
      </div>
    </div>
  );
}
