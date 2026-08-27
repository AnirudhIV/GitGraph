import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent, type WheelEvent as RWheelEvent } from "react";
import { useNavigate } from "react-router-dom";
import { authorHref, fileHref } from "../api/client";
import type { GraphEdge as ApiEdge, GraphNode as ApiNode } from "../api/types";

interface SimNode extends SimulationNodeDatum, ApiNode {}
interface SimLink extends SimulationLinkDatum<SimNode> {
  weight: number;
}

const HOP_COLOR: Record<number, string> = { 0: "var(--seq-600)", 1: "var(--seq-450)", 2: "var(--seq-300)" };
const HOP_RADIUS: Record<number, number> = { 0: 13, 1: 8, 2: 6 };

export function GraphView({ nodes, edges, height = 420 }: { nodes: ApiNode[]; edges: ApiEdge[]; height?: number }) {
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [simLinks, setSimLinks] = useState<SimLink[]>([]);
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
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

    const sim = forceSimulation(nodeCopies)
      .force("charge", forceManyBody().strength(-260))
      .force(
        "link",
        forceLink<SimNode, SimLink>(linkCopies)
          .id((d) => d.id)
          .distance((l) => 100 - Math.min(55, (l.weight ?? 1) * 8))
      )
      .force("center", forceCenter(width / 2, height / 2))
      .force("collide", forceCollide((d) => (HOP_RADIUS[(d as SimNode).hop] ?? 6) + 16))
      .stop();

    for (let i = 0; i < 260; i++) sim.tick();
    setSimNodes(nodeCopies);
    setSimLinks(linkCopies);
    setView({ x: 0, y: 0, scale: 1 });
  }, [nodes, edges, width, height]);

  const nodeById = useMemo(() => new Map(simNodes.map((n) => [n.id, n])), [simNodes]);

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

  function onWheel(e: RWheelEvent) {
    e.preventDefault();
    setView((v) => ({ ...v, scale: Math.min(2.4, Math.max(0.4, v.scale - e.deltaY * 0.001)) }));
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
        background: "var(--surface-raised)",
        touchAction: "none",
        cursor: "grab",
      }}
      onWheel={onWheel}
      onPointerDown={onContainerPointerDown}
      onPointerMove={onContainerPointerMove}
      onPointerUp={onContainerPointerUp}
      onPointerLeave={onContainerPointerUp}
    >
      <svg width="100%" height={height}>
        <g transform={`translate(${view.x},${view.y}) scale(${view.scale})`}>
          {simLinks.map((l, i) => {
            const s = typeof l.source === "object" ? l.source : nodeById.get(l.source as unknown as string);
            const t = typeof l.target === "object" ? l.target : nodeById.get(l.target as unknown as string);
            if (!s || !t || s.x == null || t.x == null || t.y == null || s.y == null) return null;
            return (
              <line
                key={i}
                x1={s.x}
                y1={s.y}
                x2={t.x}
                y2={t.y}
                stroke="var(--gridline)"
                strokeWidth={Math.max(1, Math.min(4, l.weight))}
              />
            );
          })}
          {simNodes.map((n) => (
            <g
              key={n.id}
              transform={`translate(${n.x ?? 0},${n.y ?? 0})`}
              onPointerDown={(e) => onNodePointerDown(e, n.id)}
              onClick={(e) => {
                e.stopPropagation();
                if (n.hop !== 0) navigate(n.kind === "Author" ? authorHref(n.id) : fileHref(n.id));
              }}
              style={{ cursor: n.hop === 0 ? "default" : "pointer" }}
            >
              <circle
                r={(HOP_RADIUS[n.hop] ?? 6) + n.weight * 3}
                fill={HOP_COLOR[n.hop] ?? "var(--seq-300)"}
                stroke="var(--surface-card)"
                strokeWidth={2}
              />
              <title>{n.subtitle || n.label}</title>
              <text
                x={0}
                y={(HOP_RADIUS[n.hop] ?? 6) + 15}
                textAnchor="middle"
                fontSize={10.5}
                fontFamily="var(--font-mono)"
                fill="var(--text-secondary)"
              >
                {n.label.length > 18 ? n.label.slice(0, 16) + "…" : n.label}
              </text>
            </g>
          ))}
        </g>
      </svg>
      <div style={{ position: "absolute", bottom: 10, right: 12, fontSize: 11, color: "var(--text-muted)" }}>
        drag to arrange · scroll to zoom
      </div>
    </div>
  );
}
