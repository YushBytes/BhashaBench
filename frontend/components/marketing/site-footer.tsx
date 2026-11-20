import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { docs, site, statusBadge } from "@/lib/content";

export function SiteFooter() {
  return (
    <footer data-chrome className="on-night bg-night text-night-text">
      <div className="wrap grid gap-10 py-14 md:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))]">
        <div>
          <Logo inverted />
          <p className="mt-4 max-w-xs text-[14px] leading-relaxed text-night-muted">
            Testing and benchmarking for voice AI that has to understand Indian callers.
          </p>
          <p className="mt-4 font-mono text-[12px] text-night-muted">{statusBadge}</p>
        </div>
        <FooterColumn title="Product">
          <FooterLink href="/#product">Product</FooterLink>
          <FooterLink href="/#features">Features</FooterLink>
          <FooterLink href="/#how-it-works">How it works</FooterLink>
          <FooterLink href="/#limits">What it does not do</FooterLink>
        </FooterColumn>
        <FooterColumn title="Documentation">
          {docs.map((doc) => (
            <FooterLink key={doc.href} href={doc.href} external>
              {doc.title}
            </FooterLink>
          ))}
        </FooterColumn>
        <FooterColumn title="Account">
          <FooterLink href="/signup">Create an account</FooterLink>
          <FooterLink href="/login">Sign in</FooterLink>
          <FooterLink href={site.repository} external>
            Source on GitHub
          </FooterLink>
        </FooterColumn>
      </div>
      <div className="wrap">
        <p className="border-t border-night-line py-5 text-[12px] text-night-muted">
          BhashaBench is open source. No customer logos, testimonials or usage figures appear on this site because none
          have been collected.
        </p>
      </div>
    </footer>
  );
}

function FooterColumn({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[13px] font-medium text-night-text">{title}</p>
      <ul className="mt-3 space-y-1">{children}</ul>
    </div>
  );
}

function FooterLink({ href, children, external = false }: { href: string; children: React.ReactNode; external?: boolean }) {
  const className =
    "inline-flex min-h-9 items-center text-[14px] text-night-muted underline-offset-4 transition-colors hover:text-night-text hover:underline";
  return (
    <li>
      {external ? (
        <a href={href} className={className} rel="noreferrer" target="_blank">
          {children}
        </a>
      ) : (
        <Link href={href} className={className}>
          {children}
        </Link>
      )}
    </li>
  );
}
