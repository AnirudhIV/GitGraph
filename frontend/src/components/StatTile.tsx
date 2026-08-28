export function StatTile({
  label,
  value,
  sublabel,
  valueColor,
}: {
  label: string;
  value: string | number;
  sublabel?: string;
  valueColor?: string;
}) {
  return (
    <div className="card card-pad">
      <div style={{ fontSize: 12, color: "var(--text-muted)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, marginTop: 6, letterSpacing: "-0.01em", color: valueColor }}>{value}</div>
      {sublabel && <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>{sublabel}</div>}
    </div>
  );
}
