"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { buttonClass, cx } from "@/components/ui/primitives";

const LINKS = [
  { href: "/#product", label: "Product" },
  { href: "/#features", label: "Features" },
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#docs", label: "Documentation" },
];

/**
 * The public header. On a phone the links open as a full-width panel; the
 * toggle states its own state (`aria-expanded`) and Escape closes it.
 */
export function SiteHeader() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header
      data-chrome
      className={cx(
        "sticky top-0 z-40 border-b bg-bg/85 backdrop-blur-md transition-colors",
        scrolled || open ? "border-line" : "border-transparent",
      )}
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-5 sm:px-8">
        <Logo />
        <nav aria-label="Site" className="hidden flex-1 items-center gap-1 md:flex">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-md px-3 py-2 text-[14px] text-text-2 transition-colors hover:bg-bg-sunk hover:text-text"
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto hidden items-center gap-2 md:flex">
          <Link href="/login" className={buttonClass("ghost", "md")}>
            Sign in
          </Link>
          <Link href="/signup" className={buttonClass("ink", "md")}>
            Get started
          </Link>
        </div>
        <button
          type="button"
          aria-expanded={open}
          aria-controls="site-menu"
          onClick={() => setOpen((value) => !value)}
          className="ml-auto flex size-11 items-center justify-center rounded-md text-text hover:bg-bg-sunk md:hidden"
        >
          {open ? <X aria-hidden="true" className="size-5" /> : <Menu aria-hidden="true" className="size-5" />}
          <span className="sr-only">{open ? "Close menu" : "Open menu"}</span>
        </button>
      </div>
      {open ? (
        <div id="site-menu" className="border-t border-line bg-bg px-5 pb-6 pt-2 md:hidden">
          <nav aria-label="Site" className="flex flex-col">
            {LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className="flex h-12 items-center border-b border-line text-[16px] text-text"
              >
                {link.label}
              </Link>
            ))}
          </nav>
          <div className="mt-5 grid gap-2">
            <Link href="/signup" className={buttonClass("ink", "lg", "w-full")}>
              Get started
            </Link>
            <Link href="/login" className={buttonClass("secondary", "lg", "w-full")}>
              Sign in
            </Link>
          </div>
        </div>
      ) : null}
    </header>
  );
}
