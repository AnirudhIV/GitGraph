import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState, ErrorState, LoadingRows } from "../components/StateViews";
import { useApi } from "../hooks/useApi";

export function Authors() {
  const [search, setSearch] = useState("");
  const authors = useApi(useCallback(() => api.authors(search, 60), [search]));

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Authors</h1>
        <p className="page-subtitle">Everyone who has committed, ranked by commit volume.</p>
      </div>

      <div style={{ maxWidth: 420, marginBottom: 20 }}>
        <input type="search" placeholder="Filter by name…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      <div className="card card-pad">
        {authors.loading && <LoadingRows rows={8} />}
        {authors.error && <ErrorState error={authors.error} onRetry={authors.reload} />}
        {authors.data && authors.data.length === 0 && <EmptyState title="No authors match" />}
        {authors.data && authors.data.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Author</th>
                <th>Commits</th>
                <th>Files touched</th>
                <th>Active</th>
              </tr>
            </thead>
            <tbody>
              {authors.data.map((a) => (
                <tr key={a.email}>
                  <td>
                    <Link to={`/authors/${encodeURIComponent(a.email)}`} style={{ textDecoration: "none", color: "var(--cat-1)", fontWeight: 600 }}>
                      {a.name}
                    </Link>
                  </td>
                  <td className="mono">{a.commit_count}</td>
                  <td className="mono">{a.file_count}</td>
                  <td style={{ color: "var(--text-muted)", fontSize: 12 }}>
                    {a.first_commit_at ? new Date(a.first_commit_at).getFullYear() : "—"}
                    {" – "}
                    {a.last_commit_at ? new Date(a.last_commit_at).getFullYear() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
