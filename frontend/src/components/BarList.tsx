import { Link } from "react-router-dom";

export interface BarListItem {
  key: string;
  label: string;
  sublabel?: string;
  value: number;
  href?: string;
  displayValue?: string;
}

export function BarList({ items, formatValue }: { items: BarListItem[]; formatValue?: (v: number) => string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div>
      {items.map((item) => {
        const row = (
          <div className="bar-list-row">
            <div style={{ minWidth: 0 }}>
              <div className="row-primary" style={{ fontSize: 12.5 }}>
                {item.label}
              </div>
              {item.sublabel && (
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{item.sublabel}</div>
              )}
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${(item.value / max) * 100}%` }} />
              </div>
            </div>
            <div className="bar-value">
              {item.displayValue ?? (formatValue ? formatValue(item.value) : item.value)}
            </div>
          </div>
        );
        return item.href ? (
          <Link key={item.key} to={item.href} style={{ textDecoration: "none", color: "inherit", display: "block" }}>
            {row}
          </Link>
        ) : (
          <div key={item.key}>{row}</div>
        );
      })}
    </div>
  );
}
