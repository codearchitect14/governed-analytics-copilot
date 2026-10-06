import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { BookmarkCheck, History, LayoutDashboard, LogOut, Menu, MessageSquare, Monitor, Moon, Search, Shield, Sun, X, BookOpen } from "lucide-react";
import { isAdmin, useAuth } from "../lib/auth-store";
import { logout } from "../lib/http";
import { nextTheme, useTheme, type ThemeChoice } from "../lib/theme";
import { Badge } from "../components/ui";

const MAIN_NAV = [
  { to: "/app/chat", label: "Chat", icon: MessageSquare },
  { to: "/app/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/app/catalog", label: "Catalog", icon: BookOpen },
  { to: "/app/history", label: "History", icon: History },
  { to: "/app/saved", label: "Saved", icon: BookmarkCheck },
] as const;

const ADMIN_NAV = [
  { to: "/app/admin/audit", label: "Audit explorer" },
  { to: "/app/admin/users", label: "Users and roles" },
  { to: "/app/admin/operations", label: "Operations" },
  { to: "/app/admin/evaluation", label: "Evaluation" },
] as const;

const ROLE_LABEL: Record<string, string> = {
  executive: "Executive",
  regional_manager: "Regional manager",
  category_manager: "Category manager",
  seller_partner: "Seller partner",
  analyst: "Analyst",
  admin: "Administrator",
};

const THEME_ICON: Record<ThemeChoice, typeof Sun> = { system: Monitor, light: Sun, dark: Moon };

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const user = useAuth((state) => state.user);
  return (
    <nav aria-label="Workspace" className="flex flex-col gap-1">
      {MAIN_NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-semibold no-underline ${isActive ? "bg-panel-strong text-ink" : "text-ink-muted hover:bg-panel hover:text-ink"}`
          }
        >
          <item.icon aria-hidden="true" size={18} />
          {item.label}
        </NavLink>
      ))}
      {isAdmin(user) ? (
        <div className="mt-4" role="group" aria-labelledby="admin-group">
          <p id="admin-group" className="flex items-center gap-2 px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">
            <Shield aria-hidden="true" size={14} /> Administration
          </p>
          {ADMIN_NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onNavigate}
              className={({ isActive }) =>
                `flex min-h-11 items-center rounded-md px-3 text-sm no-underline ${isActive ? "bg-panel-strong font-semibold text-ink" : "text-ink-muted hover:bg-panel hover:text-ink"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      ) : null}
    </nav>
  );
}

export default function AppShell() {
  const user = useAuth((state) => state.user);
  const navigate = useNavigate();
  const [choice, setChoice] = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const ThemeIcon = THEME_ICON[choice];

  async function signOut() {
    await logout();
    navigate("/app/login", { replace: true });
  }

  return (
    <div className="flex min-h-screen bg-page">
      <a href="#app-main" className="skip-link">Skip to content</a>

      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col gap-6 overflow-y-auto border-r border-line bg-panel p-4 md:flex">
        <Link to="/app/chat" className="px-3 text-lg font-bold text-ink no-underline">Meridian</Link>
        <Navigation />
      </aside>

      {menuOpen ? (
        <div className="fixed inset-0 z-50 flex md:hidden" role="dialog" aria-modal="true" aria-label="Workspace menu">
          <div className="w-72 max-w-[85vw] overflow-y-auto border-r border-line bg-panel p-4">
            <div className="flex items-center justify-between">
              <span className="font-bold">Meridian</span>
              <button type="button" className="min-h-11 min-w-11" aria-label="Close menu" onClick={() => setMenuOpen(false)}>
                <X aria-hidden="true" />
              </button>
            </div>
            <div className="mt-6">
              <Navigation onNavigate={() => setMenuOpen(false)} />
            </div>
          </div>
          <button type="button" className="flex-1 bg-black/40" aria-label="Close menu" onClick={() => setMenuOpen(false)} />
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex min-h-14 items-center justify-between gap-3 border-b border-line bg-page px-4">
          <div className="flex items-center gap-2">
            <button type="button" className="inline-flex min-h-11 min-w-11 items-center justify-center md:hidden" aria-label="Open menu" onClick={() => setMenuOpen(true)}>
              <Menu aria-hidden="true" />
            </button>
            <label htmlFor="global-search" className="sr-only">Search metrics and pages</label>
            <div className="relative hidden sm:block">
              <Search aria-hidden="true" size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
              <input
                id="global-search"
                type="search"
                placeholder="Search metrics and pages"
                className="min-h-11 w-64 rounded-md border border-line bg-page pl-9 pr-3 text-sm"
                onKeyDown={(event) => {
                  if (event.key === "Enter") navigate(`/app/catalog?q=${encodeURIComponent(event.currentTarget.value)}`);
                }}
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md hover:bg-panel"
              aria-label={`Theme: ${choice}. Activate to change.`}
              onClick={() => setChoice(nextTheme(choice))}
            >
              <ThemeIcon aria-hidden="true" size={18} />
            </button>
            <div className="hidden items-center gap-2 sm:flex">
              <span className="text-sm">{user?.full_name}</span>
              <Badge tone={user?.role === "admin" ? "warn" : "neutral"}>{ROLE_LABEL[user?.role ?? ""] ?? user?.role}</Badge>
            </div>
            <button type="button" onClick={signOut} className="inline-flex min-h-11 items-center gap-2 rounded-md px-3 text-sm font-semibold hover:bg-panel">
              <LogOut aria-hidden="true" size={16} />
              <span className="hidden sm:inline">Sign out</span>
              <span className="sr-only sm:hidden">Sign out</span>
            </button>
          </div>
        </header>

        <main id="app-main" tabIndex={-1} className="flex-1 p-4 focus:outline-none md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
