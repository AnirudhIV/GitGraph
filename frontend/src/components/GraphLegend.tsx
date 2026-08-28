// A small color key for GraphView instances that pass `colorForNode` --
// once that prop is set, GraphView's own built-in hop-tier legend
// (selected/direct/2nd-degree) is suppressed since it no longer describes
// what's on screen, so pages using colorForNode supply their own here.
export interface LegendItem {
  // A single token for a fixed-meaning color (e.g. a status tier), or an
  // array for a "varies by identity" swatch (a small overlapping cluster
  // standing in for an arbitrary hash-assigned color, not one true value).
  color: string | string[];
  label: string;
}

export function GraphLegend({ items }: { items: LegendItem[] }) {
  return (
    <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 10, fontSize: 11.5, color: "var(--text-muted)" }}>
      {items.map((item) => (
        <span key={item.label} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          {Array.isArray(item.color) ? (
            <span style={{ display: "inline-flex" }}>
              {item.color.map((c, i) => (
                <span
                  key={i}
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: c,
                    flex: "none",
                    marginLeft: i === 0 ? 0 : -3,
                    border: "1px solid var(--surface-card)",
                  }}
                />
              ))}
            </span>
          ) : (
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: item.color, flex: "none" }} />
          )}
          {item.label}
        </span>
      ))}
    </div>
  );
}
