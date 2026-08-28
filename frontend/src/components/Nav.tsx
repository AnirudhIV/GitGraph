import { useEffect, useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";

const LINKS = [
  { to: "/dashboard", label: "Dashboard", end: true },
  { to: "/repo-map", label: "Repo Map" },
  { to: "/files", label: "Files" },
  { to: "/authors", label: "Authors" },
  { to: "/modules", label: "Modules" },
  { to: "/collaboration", label: "Collaboration" },
];

export function Nav() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [theme, setTheme] = useState<string>(() => localStorage.getItem("theme") ?? "system");

  useEffect(() => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (query.trim()) navigate(`/search?q=${encodeURIComponent(query.trim())}`);
  }

  return (
    <nav
      style={{
        borderRight: "1px solid var(--border)",
        padding: "24px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 22,
        position: "sticky",
        top: 0,
        height: "100vh",
      }}
    >
      <Link to="/" style={{ textDecoration: "none", color: "inherit" }}>
        <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: "-0.01em" }}>GitGraph</div>
        <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 2 }}>graph over real git history</div>
      </Link>

      <form onSubmit={onSubmit}>
        <input
          type="search"
          placeholder="Search files, authors, commits…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </form>

      <NavLink
        to="/track"
        className="btn"
        style={({ isActive }) => ({
          textAlign: "center",
          textDecoration: "none",
          borderColor: isActive ? "var(--cat-1)" : undefined,
          color: isActive ? "var(--cat-1)" : undefined,
        })}
      >
        + Track a repo
      </NavLink>

      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {LINKS.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.end}
            style={({ isActive }) => ({
              padding: "8px 10px",
              borderRadius: 8,
              fontSize: 13.5,
              fontWeight: 600,
              textDecoration: "none",
              color: isActive ? "var(--cat-1)" : "var(--text-secondary)",
              background: isActive ? "color-mix(in srgb, var(--cat-1) 12%, transparent)" : "transparent",
            })}
          >
            {l.label}
          </NavLink>
        ))}
      </div>

      <div style={{ marginTop: "auto", display: "flex", gap: 4 }}>
        {(["light", "system", "dark"] as const).map((t) => (
          <button
            key={t}
            className="btn"
            onClick={() => setTheme(t)}
            style={{
              flex: 1,
              fontSize: 11,
              padding: "6px 4px",
              borderColor: theme === t ? "var(--cat-1)" : undefined,
              color: theme === t ? "var(--cat-1)" : undefined,
            }}
          >
            {t}
          </button>
        ))}
      </div>
    </nav>
  );
}
