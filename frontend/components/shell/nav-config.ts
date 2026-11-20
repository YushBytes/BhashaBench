import {
  BarChart3,
  Bot,
  FileText,
  FolderKanban,
  GitCompareArrows,
  LayoutDashboard,
  Layers,
  ListChecks,
  PlayCircle,
  Settings,
  Users,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Other paths under which this item counts as current. */
  match?: string[];
  keywords?: string;
}

/**
 * The workspace's navigation. Every entry is a route backed by real
 * endpoints; nothing here is decorative.
 */
export const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Workspace",
    items: [
      { href: "/app", label: "Overview", icon: LayoutDashboard, keywords: "dashboard home" },
      { href: "/app/projects", label: "Projects", icon: FolderKanban },
      { href: "/app/runs", label: "Test runs", icon: PlayCircle, keywords: "history results" },
    ],
  },
  {
    group: "Testing",
    items: [
      { href: "/app/scenarios", label: "Scenarios", icon: ListChecks, keywords: "builder yaml library" },
      { href: "/app/suites", label: "Test suites", icon: Layers, keywords: "bundle import export" },
      { href: "/app/bots", label: "Bots", icon: Bot, keywords: "connect chatbot integrations adapters providers speech" },
    ],
  },
  {
    group: "Insights",
    items: [
      { href: "/app/analytics", label: "Analytics", icon: BarChart3, keywords: "pass rate trend regression" },
      { href: "/app/compare", label: "Compare", icon: GitCompareArrows, keywords: "diff two runs" },
      { href: "/app/reports", label: "Reports", icon: FileText, keywords: "export csv json pdf" },
    ],
  },
  {
    group: "Administration",
    items: [
      { href: "/app/settings/team", label: "Team", icon: Users, keywords: "members roles permissions" },
      { href: "/app/settings", label: "Settings", icon: Settings, keywords: "workspace account password", match: ["/app/settings/account"] },
    ],
  },
];

export function isCurrent(item: NavItem, path: string | null): boolean {
  if (!path) return false;
  if (item.href === "/app") return path === "/app";
  if (item.href === "/app/settings") return path === "/app/settings" || (item.match ?? []).some((m) => path.startsWith(m));
  return path === item.href || path.startsWith(`${item.href}/`);
}
