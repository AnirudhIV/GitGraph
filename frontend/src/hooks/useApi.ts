import { useCallback, useEffect, useState } from "react";

interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
}

/**
 * Runs `fn` and tracks loading/error/data. Re-runs whenever `fn`'s identity
 * changes, so callers wrap `fn` in `useCallback(..., deps)` -- the
 * useCallback deps array is what actually controls re-fetching.
 */
export function useApi<T>(fn: () => Promise<T>): ApiState<T> & { reload: () => void } {
  const [state, setState] = useState<ApiState<T>>({ data: null, loading: true, error: null });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn()
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null });
      })
      .catch((error: Error) => {
        if (!cancelled) setState({ data: null, loading: false, error });
      });
    return () => {
      cancelled = true;
    };
  }, [fn, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}
