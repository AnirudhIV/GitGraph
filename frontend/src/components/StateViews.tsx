import { ApiError } from "../api/client";

export function LoadingRows({ rows = 5, height = 20 }: { rows?: number; height?: number }) {
  return (
    <div className="stack" style={{ gap: 10 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height, width: `${92 - i * 6}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="empty-state">
      <div className="empty-state-title">{title}</div>
      {subtitle && <div>{subtitle}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const unavailable = error instanceof ApiError && error.isUnavailable;
  return (
    <div className="error-state">
      <div className="error-state-title">
        {unavailable ? "The graph database is unreachable" : "Something went wrong"}
      </div>
      <div>
        {unavailable
          ? "CognoDB didn't respond. Check that the instance is running and the backend's .env credentials are correct."
          : error.message}
      </div>
      {onRetry && (
        <button className="btn" onClick={onRetry} style={{ marginTop: 8 }}>
          Retry
        </button>
      )}
    </div>
  );
}
