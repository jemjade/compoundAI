// 인증 영역의 Sidebar Layout과 하위 Page Outlet을 제공한다.
import { NavLink, Outlet, useNavigate } from "react-router";
import { setToken } from "../lib/api";

export function Layout() {
  const navigate = useNavigate();
  const logout = () => {
    setToken(null);
    navigate("/login");
  };
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">P</span>
          <span>
            <strong>ParseLab</strong>
            <small>Parser workbench</small>
          </span>
        </div>
        <nav>
          <NavLink to="/" end>
            <span>⌂</span> Overview
          </NavLink>
          <NavLink to="/documents">
            <span>▤</span> Documents
          </NavLink>
          <NavLink to="/parsers">
            <span>⌘</span> Parsers
          </NavLink>
          <NavLink to="/experiments/new">
            <span>＋</span> New experiment
          </NavLink>
        </nav>
        <div className="sidebar-foot">
          <span className="environment-dot" />
          Local environment
          <button className="text-button" onClick={logout}>
            로그아웃
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
