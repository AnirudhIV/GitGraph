import { Route, Routes } from "react-router-dom";
import { Nav } from "./components/Nav";
import { AuthorDetail } from "./pages/AuthorDetail";
import { Authors } from "./pages/Authors";
import { Collaboration } from "./pages/Collaboration";
import { Dashboard } from "./pages/Dashboard";
import { FileDetail } from "./pages/FileDetail";
import { Files } from "./pages/Files";
import { Modules } from "./pages/Modules";
import { Search } from "./pages/Search";

export default function App() {
  return (
    <div className="app-shell">
      <Nav />
      <div className="main-column">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/files" element={<Files />} />
          <Route path="/files/*" element={<FileDetail />} />
          <Route path="/authors" element={<Authors />} />
          <Route path="/authors/:email" element={<AuthorDetail />} />
          <Route path="/modules" element={<Modules />} />
          <Route path="/collaboration" element={<Collaboration />} />
          <Route path="/search" element={<Search />} />
        </Routes>
      </div>
    </div>
  );
}
