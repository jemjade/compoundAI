import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { api, setToken } from "../lib/api";
import type { User } from "../types";
import { Icon, type IconName } from "./Icon";

const navigation: Array<{
  to: string;
  label: string;
  icon: IconName;
  end?: boolean;
}> = [
  { to: "/", label: "Overview", icon: "grid", end: true },
  { to: "/documents", label: "Documents", icon: "document" },
  { to: "/tasks", label: "Tasks", icon: "tasks" },
  { to: "/parsers", label: "Parsers", icon: "parser" },
  { to: "/experiments/new", label: "Process Lab", icon: "compare" },
  { to: "/evaluation", label: "Evaluation", icon: "evaluation" },
];

function pageName(pathname: string) {
  if (pathname === "/") return "Overview";
  if (pathname.startsWith("/documents")) return "Documents";
  if (pathname.startsWith("/tasks")) return "Tasks";
  if (pathname.startsWith("/parsers/new")) return "Register parser";
  if (pathname.startsWith("/parsers/")) return "Parser profile";
  if (pathname.startsWith("/parsers")) return "Parsers";
  if (pathname.includes("/compare")) return "Comparison workspace";
  if (pathname.startsWith("/experiments/new")) return "New task";
  if (pathname.startsWith("/experiments/")) return "Task detail";
  if (pathname.startsWith("/evaluation")) return "Evaluation";
  return "ParseLab";
}

export function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("parselab_sidebar") === "collapsed",
  );
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const paletteRef = useRef<HTMLDivElement>(null);
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/users/me"),
  });
  const currentPage = useMemo(() => pageName(location.pathname), [location.pathname]);

  useEffect(() => {
    setMobileOpen(false);
    setPaletteOpen(false);
    setUserOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const openPalette = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", openPalette);
    return () => window.removeEventListener("keydown", openPalette);
  }, []);

  useEffect(() => {
    if (!paletteOpen) return;
    paletteRef.current?.querySelector<HTMLElement>("a, button")?.focus();
    const handleKeys = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPaletteOpen(false);
        return;
      }
      if (event.key !== "Tab" || !paletteRef.current) return;
      const focusable = Array.from(
        paletteRef.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handleKeys);
    return () => window.removeEventListener("keydown", handleKeys);
  }, [paletteOpen]);

  const toggleCollapsed = () => {
    setCollapsed((current) => {
      localStorage.setItem("parselab_sidebar", current ? "expanded" : "collapsed");
      return !current;
    });
  };
  const logout = () => {
    setToken(null);
    navigate("/login");
  };

  return (
    <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      <aside className={`sidebar ${mobileOpen ? "mobile-open" : ""}`} aria-label="주 탐색">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><Icon name="layers" size={20} /></span>
          <span className="brand-copy">
            <strong>ParseLab</strong>
            <small>Document intelligence</small>
          </span>
          <button
            type="button"
            className="sidebar-collapse"
            onClick={toggleCollapsed}
            aria-label={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
          >
            <Icon name={collapsed ? "arrowRight" : "arrowLeft"} size={15} />
          </button>
        </div>
        <nav>
          <span className="nav-label">Workspace</span>
          {navigation.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              title={collapsed ? item.label : undefined}
            >
              <Icon name={item.icon} size={17} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-context">
          <div className="context-heading">
            <span className="environment-dot" />
            <span>System online</span>
          </div>
          <p>Local environment</p>
          <div className="context-metric">
            <span>API</span>
            <strong>Connected</strong>
          </div>
        </div>
        <div className="sidebar-foot">
          <div className="sidebar-avatar">{me.data?.name?.slice(0, 1).toUpperCase() ?? "P"}</div>
          <div className="sidebar-user">
            <strong>{me.data?.name ?? "ParseLab user"}</strong>
            <span>{me.data?.role ?? "USER"}</span>
          </div>
          <button type="button" onClick={logout} aria-label="로그아웃" title="로그아웃">
            <Icon name="logout" size={16} />
          </button>
        </div>
      </aside>

      {mobileOpen && (
        <button
          type="button"
          className="sidebar-scrim"
          aria-label="메뉴 닫기"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-title">
            <button
              type="button"
              className="mobile-menu"
              onClick={() => setMobileOpen(true)}
              aria-label="메뉴 열기"
            >
              <Icon name="menu" size={19} />
            </button>
            <span>Workspace</span>
            <Icon name="arrowRight" size={13} />
            <strong>{currentPage}</strong>
          </div>
          <div className="topbar-actions">
            <button
              type="button"
              className="command-trigger"
              onClick={() => setPaletteOpen(true)}
              aria-haspopup="dialog"
            >
              <Icon name="search" size={15} />
              <span>Search workspace</span>
              <kbd>⌘ K</kbd>
            </button>
            <span className="system-status"><span className="environment-dot" /> Operational</span>
            <div className="user-menu-wrap">
              <button
                type="button"
                className="user-trigger"
                aria-expanded={userOpen}
                aria-label="사용자 메뉴"
                onClick={() => setUserOpen((current) => !current)}
              >
                <span>{me.data?.name?.slice(0, 1).toUpperCase() ?? "P"}</span>
                <Icon name="chevronDown" size={13} />
              </button>
              {userOpen && (
                <div className="user-menu" role="menu">
                  <div>
                    <strong>{me.data?.name ?? "ParseLab user"}</strong>
                    <span>{me.data?.email}</span>
                  </div>
                  <button type="button" onClick={logout} role="menuitem">
                    <Icon name="logout" size={15} /> 로그아웃
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>

      {paletteOpen && (
        <div
          className="dialog-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) setPaletteOpen(false);
          }}
        >
          <div
            className="command-palette"
            role="dialog"
            aria-modal="true"
            aria-label="워크스페이스 빠른 이동"
            ref={paletteRef}
          >
            <div className="command-input">
              <Icon name="search" size={17} />
              <span>빠른 이동</span>
              <button type="button" onClick={() => setPaletteOpen(false)} aria-label="닫기">
                <Icon name="x" size={16} />
              </button>
            </div>
            <div className="command-group">
              <span>Pages</span>
              {navigation.map((item) => (
                <NavLink key={item.to} to={item.to}>
                  <Icon name={item.icon} size={17} />
                  <span>{item.label}</span>
                  <Icon name="arrowRight" size={14} />
                </NavLink>
              ))}
            </div>
            <p><kbd>ESC</kbd> 닫기 · 페이지를 선택해 이동</p>
          </div>
        </div>
      )}
    </div>
  );
}
