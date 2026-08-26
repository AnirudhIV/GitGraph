import { useNavigate } from "react-router-dom";
import { Landing } from "./Landing";

export function TrackRepo() {
  const navigate = useNavigate();

  return (
    <div>
      <div style={{ maxWidth: 640, margin: "0 auto 12px", fontSize: 12.5, color: "var(--status-serious)" }}>
        Tracking a new repository replaces the graph currently loaded — existing files, authors and commits will be
        gone.
      </div>
      <Landing onTracked={() => navigate("/")} />
    </div>
  );
}
