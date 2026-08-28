import { useCallback } from "react";
import { Outlet, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import { Nav } from "./components/Nav";
import { useApi } from "./hooks/useApi";
import { AuthorDetail } from "./pages/AuthorDetail";
import { Authors } from "./pages/Authors";
import { Collaboration } from "./pages/Collaboration";
import { Dashboard } from "./pages/Dashboard";
import { FileDetail } from "./pages/FileDetail";
import { Files } from "./pages/Files";
import { Home } from "./pages/Home";
import { Landing } from "./pages/Landing";
import { Modules } from "./pages/Modules";
import { RepoMap } from "./pages/RepoMap";
import { Search } from "./pages/Search";
import { TrackRepo } from "./pages/TrackRepo";

function AppShell() {
  const stats = useApi(useCallback(() => api.stats(), []));

  // Nothing tracked yet: show the standalone onboarding form, no app chrome
  // (sidebar nav to pages with no data, search box, theme toggle). Falls
  // through to the normal shell while stats are loading or errored, so
  // Dashboard's own loading/error states still handle those cases.
  if (stats.data && stats.data.file_count === 0) {
    return <Landing onTracked={stats.reload} />;
  }

  return (
    <div className="app-shell">
      <Nav />
      <div className="main-column">
        <Outlet />
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route element={<AppShell />}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/repo-map" element={<RepoMap />} />
        <Route path="/files" element={<Files />} />
        <Route path="/files/*" element={<FileDetail />} />
        <Route path="/authors" element={<Authors />} />
        <Route path="/authors/:email" element={<AuthorDetail />} />
        <Route path="/modules" element={<Modules />} />
        <Route path="/collaboration" element={<Collaboration />} />
        <Route path="/search" element={<Search />} />
        <Route path="/track" element={<TrackRepo />} />
      </Route>
    </Routes>
  );
}
