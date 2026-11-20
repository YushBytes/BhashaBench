import Link from "next/link";

import { cx } from "@/components/ui/primitives";

const ITEMS = [
  { href: "/app/settings", label: "Workspace" },
  { href: "/app/settings/team", label: "Team and roles" },
  { href: "/app/settings/account", label: "Account and security" },
] as const;

export function SettingsNav({ current }: { current: (typeof ITEMS)[number]["href"] }) {
  return (
    <nav aria-label="Settings" className="-mt-2 flex gap-1 overflow-x-auto border-b border-line">
      {ITEMS.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          aria-current={item.href === current ? "page" : undefined}
          className={cx(
            "-mb-px inline-flex h-10 shrink-0 items-center border-b-2 px-3 text-[13px] font-medium",
            item.href === current ? "border-accent text-text" : "border-transparent text-text-3 hover:text-text",
          )}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
