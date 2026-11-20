"use client";

/**
 * The workspace chrome: a collapsible sidebar on wide screens, a top bar and
 * a drawer on narrow ones, and a command menu on Ctrl/⌘ K.
 *
 * The drawer and the command menu are native `<dialog>`s: the browser traps
 * focus, makes the page behind inert, closes on Escape and returns focus.
 * The collapsed state is a per-browser preference in localStorage, read
 * after mount so the server render and the first client render agree.
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronsLeft, ChevronsRight, CornerDownLeft, Menu, Plus, Search, X } from "lucide-react";

import { Logo, LogoMark } from "@/components/brand/logo";
import { buttonClass, cx } from "@/components/ui/primitives";
import { NAV, isCurrent, type NavItem } from "./nav-config";

const COLLAPSE_KEY = "bb.sidebar.collapsed";

/**
 * The current path, read inside its own Suspense boundary: under Cache
 * Components `usePathname()` is request-time data, and reading it in the
 * shell itself would make every page's chrome block the prerender.
 */
function WithPath({ children }: { children: (path: string | null) => ReactNode }) {
  return <>{children(usePathname())}</>;
}

function OnRouteChange({ run }: { run: () => void }) {
  const path = usePathname();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => run(), [path]);
  return null;
}

function PathAware({ children }: { children: (path: string | null) => ReactNode }) {
  return (
    <Suspense fallback={children(null)}>
      <WithPath>{children}</WithPath>
    </Suspense>
  );
}

export function Shell({ account, children }: { account: ReactNode; children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);

  useEffect(() => {
    // A preference read once after mount, so the first render matches the server's.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((value) => !value);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);


  function toggle() {
    setCollapsed((value) => {
      window.localStorage.setItem(COLLAPSE_KEY, value ? "0" : "1");
      return !value;
    });
  }

  return (
    <div className="flex min-h-dvh bg-bg-soft">
      <aside
        data-chrome
        aria-label="Workspace"
        className={cx(
          "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-line bg-bg transition-[width] duration-200 lg:flex",
          collapsed ? "w-[68px]" : "w-64",
        )}
      >
        <div className={cx("flex h-14 items-center border-b border-line", collapsed ? "justify-center px-2" : "justify-between px-4")}>
          {collapsed ? (
            <Link href="/app" className="rounded-md">
              <LogoMark />
              <span className="sr-only">BhashaBench overview</span>
            </Link>
          ) : (
            <Logo href="/app" />
          )}
          {collapsed ? null : (
            <button
              type="button"
              onClick={toggle}
              className="flex size-8 items-center justify-center rounded-md text-text-3 hover:bg-bg-sunk hover:text-text"
            >
              <ChevronsLeft aria-hidden="true" className="size-4" />
              <span className="sr-only">Collapse sidebar</span>
            </button>
          )}
        </div>
        <PathAware>{(path) => <SidebarBody path={path} collapsed={collapsed} onSearch={() => setPalette(true)} />}</PathAware>
        <div className="border-t border-line p-2">
          {collapsed ? (
            <button
              type="button"
              onClick={toggle}
              title="Expand sidebar"
              className="flex h-9 w-full items-center justify-center rounded-md text-text-3 hover:bg-bg-sunk hover:text-text"
            >
              <ChevronsRight aria-hidden="true" className="size-4" />
              <span className="sr-only">Expand sidebar</span>
            </button>
          ) : (
            account
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header data-chrome className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-line bg-bg/90 px-3 backdrop-blur-md lg:hidden">
          <button
            type="button"
            onClick={() => setDrawer(true)}
            aria-expanded={drawer}
            aria-controls="nav-drawer"
            className="flex size-11 items-center justify-center rounded-md text-text hover:bg-bg-sunk"
          >
            <Menu aria-hidden="true" className="size-5" />
            <span className="sr-only">Open navigation</span>
          </button>
          <Logo href="/app" />
          <button
            type="button"
            onClick={() => setPalette(true)}
            className="ml-auto flex size-11 items-center justify-center rounded-md text-text-2 hover:bg-bg-sunk"
          >
            <Search aria-hidden="true" className="size-5" />
            <span className="sr-only">Search pages</span>
          </button>
        </header>
        {children}
      </div>

      <Drawer open={drawer} onClose={() => setDrawer(false)}>
        <PathAware>
          {(path) => (
            <SidebarBody
              path={path}
              collapsed={false}
              onSearch={() => {
                setDrawer(false);
                setPalette(true);
              }}
            />
          )}
        </PathAware>
        <div className="border-t border-line p-2">{account}</div>
      </Drawer>

      <CommandPalette open={palette} onClose={() => setPalette(false)} />
      <Suspense fallback={null}>
        <OnRouteChange run={() => setDrawer(false)} />
      </Suspense>
    </div>
  );
}

function SidebarBody({ path, collapsed, onSearch }: { path: string | null; collapsed: boolean; onSearch: () => void }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className={cx("space-y-2 p-3", collapsed && "px-2")}>
        <Link
          href="/app/runs/new"
          title={collapsed ? "New test run" : undefined}
          className={buttonClass("primary", "md", cx("w-full", collapsed && "px-0"))}
        >
          <Plus aria-hidden="true" className="size-4" />
          {collapsed ? <span className="sr-only">New test run</span> : "New test run"}
        </Link>
        <button
          type="button"
          onClick={onSearch}
          title={collapsed ? "Search (Ctrl K)" : undefined}
          className={cx(
            "flex h-9 w-full items-center gap-2 rounded-md border border-line bg-bg-soft text-[13px] text-text-3 transition-colors hover:border-line-strong hover:text-text",
            collapsed ? "justify-center" : "px-2.5",
          )}
        >
          <Search aria-hidden="true" className="size-4" />
          {collapsed ? <span className="sr-only">Search pages</span> : (
            <>
              Jump to…
              <span className="ml-auto font-mono text-[11px]">Ctrl K</span>
            </>
          )}
        </button>
      </div>
      <nav aria-label="Main" className={cx("flex-1 pb-4", collapsed ? "px-2" : "px-3")}>
        {NAV.map((section) => (
          <div key={section.group} className="mt-3 first:mt-1">
            {collapsed ? (
              <div className="mx-2 my-2 h-px bg-line" aria-hidden="true" />
            ) : (
              <p className="px-2 pb-1.5 pt-2 text-[11px] font-medium uppercase tracking-[0.08em] text-text-3">{section.group}</p>
            )}
            <ul className="space-y-0.5">
              {section.items.map((item) => (
                <li key={item.href}>
                  <NavLink item={item} current={isCurrent(item, path)} collapsed={collapsed} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </div>
  );
}

function NavLink({ item, current, collapsed }: { item: NavItem; current: boolean; collapsed: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={current ? "page" : undefined}
      title={collapsed ? item.label : undefined}
      className={cx(
        "group relative flex h-9 items-center gap-2.5 rounded-md text-[14px] transition-colors",
        collapsed ? "justify-center" : "px-2.5",
        current ? "bg-bg-sunk font-medium text-text" : "text-text-2 hover:bg-bg-sunk/70 hover:text-text",
      )}
    >
      {current ? <span aria-hidden="true" className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent" /> : null}
      <Icon aria-hidden="true" className={cx("size-4 shrink-0", current ? "text-text" : "text-text-3 group-hover:text-text-2")} strokeWidth={1.75} />
      {collapsed ? <span className="sr-only">{item.label}</span> : item.label}
    </Link>
  );
}

function Drawer({ open, onClose, children }: { open: boolean; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement | null>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      id="nav-drawer"
      aria-label="Navigation"
      onClose={onClose}
      onClick={(event) => event.target === ref.current && onClose()}
      className="m-0 h-dvh max-h-none w-[min(20rem,86vw)] border-r border-line bg-bg p-0 backdrop:bg-black/40"
    >
      <div className="flex h-full flex-col">
        <div className="flex h-14 items-center justify-between border-b border-line px-4">
          <Logo href="/app" />
          <button type="button" onClick={onClose} className="flex size-11 items-center justify-center rounded-md text-text-3 hover:bg-bg-sunk hover:text-text">
            <X aria-hidden="true" className="size-5" />
            <span className="sr-only">Close navigation</span>
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}

const ACTIONS: { href: string; label: string; keywords: string }[] = [
  { href: "/app/runs/new", label: "Start a new test run", keywords: "run execute launch" },
  { href: "/app/scenarios/new", label: "Build a new scenario", keywords: "create author yaml" },
  { href: "/app/suites?create=1", label: "Create a test suite", keywords: "new suite" },
  { href: "/app/projects?create=1", label: "Create a project", keywords: "new project" },
  { href: "/app/settings/account", label: "Change your password", keywords: "security account" },
];

/** Jump to a page or an action. Filtering is local; every target is a real route. */
function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const ref = useRef<HTMLDialogElement | null>(null);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);

  const entries = useMemo(() => {
    const all = [
      ...ACTIONS.map((a) => ({ ...a, group: "Actions" })),
      ...NAV.flatMap((s) => s.items.map((i) => ({ href: i.href, label: i.label, keywords: i.keywords ?? "", group: s.group }))),
    ];
    const q = query.trim().toLowerCase();
    return q ? all.filter((e) => `${e.label} ${e.keywords} ${e.group}`.toLowerCase().includes(q)) : all;
  }, [query]);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (open && !node.open) {
      setQuery("");
      setIndex(0);
      node.showModal();
    }
    if (!open && node.open) node.close();
  }, [open]);

  function go(href: string) {
    onClose();
    router.push(href);
  }

  const active = Math.min(index, Math.max(entries.length - 1, 0));

  return (
    <dialog
      ref={ref}
      aria-label="Jump to a page"
      onClose={onClose}
      onClick={(event) => event.target === ref.current && onClose()}
      className="mx-auto mt-[12vh] w-[calc(100%-1.5rem)] max-w-lg rounded-xl border border-line bg-bg p-0 shadow-pop backdrop:bg-black/30"
    >
      <div className="flex items-center gap-2 border-b border-line px-4">
        <Search aria-hidden="true" className="size-4 text-text-3" />
        <input
          autoFocus
          value={query}
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
          aria-activedescendant={entries[active] ? `palette-${active}` : undefined}
          aria-label="Search pages and actions"
          placeholder="Search pages and actions"
          onChange={(event) => {
            setQuery(event.target.value);
            setIndex(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setIndex((i) => Math.min(i + 1, entries.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setIndex((i) => Math.max(i - 1, 0));
            } else if (event.key === "Enter" && entries[active]) {
              event.preventDefault();
              go(entries[active].href);
            }
          }}
          className="h-12 min-w-0 flex-1 bg-transparent text-[15px] text-text outline-none placeholder:text-text-3 focus-visible:outline-none"
        />
      </div>
      <ul id="palette-list" role="listbox" aria-label="Results" className="max-h-80 overflow-y-auto p-2">
        {entries.length === 0 ? (
          <li className="px-3 py-6 text-center text-[13px] text-text-3">Nothing matches &ldquo;{query}&rdquo;.</li>
        ) : (
          entries.map((entry, i) => (
            <li
              key={`${entry.group}-${entry.href}`}
              id={`palette-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseEnter={() => setIndex(i)}
              onClick={() => go(entry.href)}
              className={cx(
                "flex cursor-pointer items-center justify-between gap-3 rounded-md px-3 py-2.5 text-[14px]",
                i === active ? "bg-bg-sunk text-text" : "text-text-2",
              )}
            >
              <span>{entry.label}</span>
              <span className="flex items-center gap-2 text-[12px] text-text-3">
                {entry.group}
                {i === active ? <CornerDownLeft aria-hidden="true" className="size-3.5" /> : null}
              </span>
            </li>
          ))
        )}
      </ul>
    </dialog>
  );
}
