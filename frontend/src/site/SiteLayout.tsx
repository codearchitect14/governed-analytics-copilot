import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { Menu, Monitor, Moon, Sun, X } from "lucide-react";
import { ANNOUNCEMENT, PRODUCT_NAME } from "../lib/content";
import { nextTheme, useTheme, type ThemeChoice } from "../lib/theme";
import { LinkButton } from "../components/ui";

const NAV = [
  { to: "/platform", label: "Platform" },
  { to: "/solutions", label: "Solutions" },
  { to: "/security", label: "Security" },
  { to: "/benchmarks", label: "Benchmarks" },
  { to: "/resources", label: "Resources" },
] as const;

const THEME_ICON: Record<ThemeChoice, typeof Sun> = { system: Monitor, light: Sun, dark: Moon };
const THEME_LABEL: Record<ThemeChoice, string> = { system: "System theme", light: "Light theme", dark: "Dark theme" };

function ThemeToggle() {
  const [choice, setChoice] = useTheme();
  const Icon = THEME_ICON[choice];
  return (
    <button
      type="button"
      onClick={() => setChoice(nextTheme(choice))}
      aria-label={`Theme: ${THEME_LABEL[choice]}. Activate to change.`}
      title={THEME_LABEL[choice]}
      className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md text-ink hover:bg-panel"
    >
      <Icon aria-hidden="true" size={20} />
    </button>
  );
}

function SiteHeader() {
  const [open, setOpen] = useState(false);
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-page/95 backdrop-blur">
      <div className="container-page flex min-h-16 items-center justify-between gap-4 py-2">
        <Link to="/" className="flex items-center gap-2 text-lg font-bold text-ink no-underline" aria-label={`${PRODUCT_NAME} home`}>
          <span aria-hidden="true" className="inline-block h-7 w-7 rounded-md bg-brand" />
          <span>Meridian</span>
        </Link>

        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `min-h-11 inline-flex items-center rounded-md px-3 text-sm font-semibold no-underline ${isActive ? "text-ink" : "text-ink-muted hover:text-ink"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Link to="/app/login" className="hidden min-h-11 items-center px-3 text-sm font-semibold text-ink no-underline sm:inline-flex">
            Sign in
          </Link>
          <LinkButton to="/contact" variant="accent" className="hidden sm:inline-flex">
            Request a demo
          </LinkButton>
          <button
            type="button"
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md text-ink md:hidden"
            aria-expanded={open}
            aria-controls="mobile-nav"
            aria-label={open ? "Close menu" : "Open menu"}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
          </button>
        </div>
      </div>

      {open ? (
        <nav id="mobile-nav" aria-label="Main mobile" className="border-t border-line bg-page md:hidden">
          <ul className="container-page flex flex-col py-2">
            {NAV.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} onClick={() => setOpen(false)} className="flex min-h-11 items-center text-base font-semibold text-ink no-underline">
                  {item.label}
                </NavLink>
              </li>
            ))}
            <li>
              <Link to="/app/login" onClick={() => setOpen(false)} className="flex min-h-11 items-center text-base font-semibold text-ink no-underline">
                Sign in
              </Link>
            </li>
            <li className="py-2">
              <LinkButton to="/contact" variant="accent" className="w-full">
                Request a demo
              </LinkButton>
            </li>
          </ul>
        </nav>
      ) : null}
    </header>
  );
}

function SiteFooter() {
  const columns = [
    { title: "Product", links: [{ to: "/platform", label: "Platform" }, { to: "/solutions", label: "Solutions" }, { to: "/benchmarks", label: "Benchmarks" }] },
    { title: "Company", links: [{ to: "/about", label: "About" }, { to: "/contact", label: "Contact" }] },
    { title: "Resources", links: [{ to: "/resources", label: "Documentation" }, { to: "/security", label: "Security" }] },
    {
      title: "Legal",
      links: [
        { to: "/legal/privacy", label: "Privacy" },
        { to: "/legal/terms", label: "Terms" },
        { to: "/legal/cookies", label: "Cookie notice" },
        { to: "/legal/accessibility", label: "Accessibility" },
        { to: "/legal/attribution", label: "Data attribution" },
      ],
    },
  ];
  return (
    <footer className="mt-16 border-t border-line bg-panel">
      <div className="container-page grid gap-8 py-12 sm:grid-cols-2 lg:grid-cols-4">
        {columns.map((column) => (
          <div key={column.title}>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">{column.title}</h2>
            <ul className="mt-3 flex flex-col gap-2">
              {column.links.map((link) => (
                <li key={link.to}>
                  <Link to={link.to} className="text-sm text-ink no-underline hover:underline">
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="container-page flex flex-col gap-2 border-t border-line py-6 text-xs text-ink-muted sm:flex-row sm:justify-between">
        <p>© {new Date().getFullYear()} {PRODUCT_NAME}. Demonstration only.</p>
        <p>
          Dataset: Olist Brazilian E-Commerce (Kaggle), CC BY-NC-SA 4.0. Attribution on the{" "}
          <Link to="/legal/attribution">data attribution page</Link>.
        </p>
      </div>
    </footer>
  );
}

export default function SiteLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <div role="note" className="bg-brand px-4 py-2 text-center text-xs text-on-brand">
        {ANNOUNCEMENT}
      </div>
      <SiteHeader />
      <main id="main" tabIndex={-1} className="flex-1 focus:outline-none">
        <Outlet />
      </main>
      <SiteFooter />
    </div>
  );
}
