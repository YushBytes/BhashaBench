import { Check } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { languages } from "@/lib/content";

/**
 * The sign-in and sign-up frame: the form on the left, and on a wide screen
 * a dark panel that says what the account is for. No testimonial, no usage
 * figure - there are none to quote.
 */
export function AuthShell({
  title,
  description,
  children,
  aside,
}: {
  title: string;
  description: React.ReactNode;
  children: React.ReactNode;
  aside: { title: string; points: string[] };
}) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <main id="main" className="flex flex-col px-5 py-6 sm:px-10">
        <Logo />
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-12">
          <h1 className="text-[28px] font-medium leading-tight tracking-[-0.035em] text-text">{title}</h1>
          <div className="mt-2 text-[14px] leading-relaxed text-text-3">{description}</div>
          <div className="mt-8">{children}</div>
        </div>
      </main>
      <aside className="on-night relative hidden overflow-hidden bg-night text-night-text lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="relative max-w-md">
          <p className="text-[24px] font-medium leading-snug tracking-[-0.03em]">{aside.title}</p>
          <ul className="mt-8 space-y-4">
            {aside.points.map((point) => (
              <li key={point} className="flex gap-3 text-[15px] leading-relaxed text-night-muted">
                <Check aria-hidden="true" className="mt-1 size-4 shrink-0 text-night-accent" />
                {point}
              </li>
            ))}
          </ul>
        </div>
        <ul aria-hidden="true" className="relative mt-12 flex flex-wrap gap-x-5 gap-y-3 text-[22px] text-night-text/25">
          {languages.map((language) => (
            <li key={language.code} lang={language.code}>
              {language.endonym}
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}
