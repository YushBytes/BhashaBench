import Link from "next/link";
import {
  ArrowRight,
  AudioLines,
  BookOpen,
  CircleSlash,
  FileDown,
  GitCompareArrows,
  Languages,
  ListChecks,
  MessagesSquare,
  Mic,
  PhoneOff,
  Plug,
  Scale,
  SlidersHorizontal,
  SpellCheck,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import { ProductPreview } from "@/components/marketing/product-preview";
import { SiteFooter } from "@/components/marketing/site-footer";
import { SiteHeader } from "@/components/marketing/site-header";
import { buttonClass, cx } from "@/components/ui/primitives";
import { docs, features, languages, limitations, statusBadge, unmeasuredQualities, unmeasuredReason } from "@/lib/content";

export const metadata = {
  title: { absolute: "BhashaBench — test voice AI on how India actually speaks" },
};

const FEATURE_ICON: Record<string, LucideIcon> = {
  languages: Languages,
  conditions: SlidersHorizontal,
  accent: Mic,
  "barge-in": AudioLines,
  "code-mixing": SpellCheck,
  wer: ListChecks,
  evaluation: Scale,
  comparison: GitCompareArrows,
  reports: FileDown,
};

const STEPS: { title: string; body: string; icon: LucideIcon }[] = [
  {
    title: "Connect your voice bot",
    body: "Point a run at your bot over the HTTP text protocol or the streaming voice WebSocket. Both are published in the repository.",
    icon: Plug,
  },
  {
    title: "Configure test scenarios",
    body: "Write who calls, what they want, the facts they may give and the outcomes your bot must reach, or start from the reference library.",
    icon: ListChecks,
  },
  {
    title: "Run realistic conversations",
    body: "The caller speaks, the line degrades it, your bot answers, and the caller decides its next turn from what the bot actually said.",
    icon: MessagesSquare,
  },
  {
    title: "Evaluate results",
    body: "Each run gets a verdict with a reason for every criterion. WER and CER appear once a reviewer records what the bot really said.",
    icon: Scale,
  },
  {
    title: "Compare performance",
    body: "Put two runs side by side, or test whether this week's pass rate really fell against last week's before calling it a regression.",
    icon: GitCompareArrows,
  },
  {
    title: "Improve your voice AI",
    body: "Replay the exact turn that failed, with its audio, its transcript and the stage that took the time, then run it again with the same seed.",
    icon: TrendingUp,
  },
];

export default function HomePage() {
  return (
    <>
      <SiteHeader />
      <main id="main">
        {/* 1. Hero */}
        <section id="product" className="relative overflow-hidden border-b border-line">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,var(--line)_1px,transparent_1px),linear-gradient(to_bottom,var(--line)_1px,transparent_1px)] bg-[size:56px_56px] [mask-image:radial-gradient(ellipse_at_top,black_20%,transparent_70%)] opacity-60"
          />
          <div className="relative mx-auto max-w-6xl px-5 pb-16 pt-14 sm:px-8 sm:pt-20 lg:pb-24">
            <p className="bb-enter inline-flex items-center gap-2 rounded-full border border-line bg-bg px-3 py-1 font-mono text-[12px] text-text-2">
              <span className="size-1.5 rounded-full bg-accent" aria-hidden="true" />
              13 Indian languages · G.711 line conditions · WER per script
            </p>
            <h1 className="bb-enter bb-enter-2 mt-6 max-w-4xl text-[clamp(2.4rem,6vw,4.25rem)] font-medium leading-[1.02] tracking-[-0.045em] text-text">
              Test your voice bot the way India actually talks.
            </h1>
            <p className="bb-enter bb-enter-3 mt-6 max-w-2xl text-[17px] leading-relaxed text-text-2 sm:text-[18px]">
              BhashaBench calls your bot in Tamil, Hindi, Bengali and ten more languages, puts the line through codecs,
              jitter and noise, and hands back every turn with its recording, transcript and measured error rate.
            </p>
            <div className="bb-enter bb-enter-3 mt-8 flex flex-col gap-3 sm:flex-row">
              <Link href="/signup" className={buttonClass("primary", "lg")}>
                Create an account
                <ArrowRight aria-hidden="true" className="size-4" />
              </Link>
              <Link href="#how-it-works" className={buttonClass("secondary", "lg")}>
                See how a test runs
              </Link>
            </div>
            <div className="bb-enter bb-enter-4 mt-14">
              <ProductPreview />
            </div>
          </div>
        </section>

        {/* 2. Languages */}
        <section aria-labelledby="languages-title" className="on-night bg-night text-night-text">
          <div className="mx-auto max-w-6xl px-5 py-20 sm:px-8 lg:py-28">
            <div className="grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
              <div>
                <h2 id="languages-title" className="text-[clamp(1.9rem,3.6vw,2.75rem)] font-medium leading-[1.08] tracking-[-0.035em]">
                  Thirteen languages, each in its own script.
                </h2>
                <p className="mt-5 max-w-md text-[16px] leading-relaxed text-night-muted">
                  Scenarios are written in the language the caller speaks, and transcripts are tagged with it, so a
                  screen reader reads Tamil as Tamil. Ten are covered end to end by Gnani&rsquo;s speech engines. Urdu,
                  Odia and Assamese can be authored but no provider transcribes them yet.
                </p>
              </div>
              <ul className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-night-line bg-night-line sm:grid-cols-3">
                {languages.map((language) => (
                  <li key={language.code} className="bg-night px-4 py-5">
                    <p lang={language.code} className="text-[22px] leading-tight text-night-text sm:text-[24px]">
                      {language.endonym}
                    </p>
                    <p className="mt-2 flex flex-wrap items-center gap-x-2 font-mono text-[11px] text-night-muted">
                      <span>{language.code}</span>
                      <span>{language.script}</span>
                      {language.transcribable ? null : <span className="text-[#f5b971]">authoring only</span>}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        {/* 3. Features */}
        <section id="features" aria-labelledby="features-title" className="border-b border-line">
          <div className="mx-auto max-w-6xl px-5 py-20 sm:px-8 lg:py-28">
            <div className="max-w-2xl">
              <h2 id="features-title" className="text-[clamp(1.9rem,3.6vw,2.75rem)] font-medium leading-[1.08] tracking-[-0.035em]">
                What a test run measures.
              </h2>
              <p className="mt-4 text-[16px] leading-relaxed text-text-2">
                Each capability is marked with what it does today. Where one is limited, the limit is written next to it.
              </p>
            </div>
            <ul className="mt-12 grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
              {features.map((feature) => {
                const Icon = FEATURE_ICON[feature.key] ?? ListChecks;
                return (
                  <li key={feature.key} className="flex flex-col bg-bg p-6 transition-colors hover:bg-bg-soft">
                    <div className="flex items-center justify-between gap-3">
                      <span className="flex size-9 items-center justify-center rounded-md border border-line bg-bg-soft">
                        <Icon aria-hidden="true" className="size-4.5 text-text" strokeWidth={1.75} />
                      </span>
                      <span
                        className={cx(
                          "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                          feature.status === "built"
                            ? "border-ok/25 bg-ok-soft text-ok"
                            : "border-warn/25 bg-warn-soft text-warn",
                        )}
                      >
                        {feature.status === "built" ? "Available" : "Limited"}
                      </span>
                    </div>
                    <h3 className="mt-5 text-[16px] font-semibold tracking-[-0.01em] text-text">{feature.title}</h3>
                    <p className="mt-2 text-[14px] leading-relaxed text-text-2">{feature.body}</p>
                    {feature.limit ? (
                      <p className="mt-3 border-t border-line pt-3 text-[13px] leading-relaxed text-text-3">{feature.limit}</p>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </div>
        </section>

        {/* 4. How it works */}
        <section id="how-it-works" aria-labelledby="how-title" className="border-b border-line bg-bg-soft">
          <div className="mx-auto max-w-6xl px-5 py-20 sm:px-8 lg:py-28">
            <h2 id="how-title" className="max-w-2xl text-[clamp(1.9rem,3.6vw,2.75rem)] font-medium leading-[1.08] tracking-[-0.035em]">
              Six steps from a scenario to a fix.
            </h2>
            <ol className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {STEPS.map((step, index) => (
                <li key={step.title} className="rounded-xl border border-line bg-bg p-6 shadow-1">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-[12px] text-text-3">{String(index + 1).padStart(2, "0")}</span>
                    <span className="h-px flex-1 bg-line" aria-hidden="true" />
                    <step.icon aria-hidden="true" className="size-4 text-text-3" strokeWidth={1.75} />
                  </div>
                  <h3 className="mt-4 text-[16px] font-semibold tracking-[-0.01em]">{step.title}</h3>
                  <p className="mt-2 text-[14px] leading-relaxed text-text-2">{step.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* 5. Evidence */}
        <section aria-labelledby="evidence-title" className="border-b border-line">
          <div className="mx-auto grid max-w-6xl gap-12 px-5 py-20 sm:px-8 lg:grid-cols-2 lg:gap-16 lg:py-28">
            <div>
              <h2 id="evidence-title" className="text-[clamp(1.9rem,3.6vw,2.75rem)] font-medium leading-[1.08] tracking-[-0.035em]">
                A missing number stays missing.
              </h2>
              <p className="mt-5 max-w-lg text-[16px] leading-relaxed text-text-2">
                A bot that said nothing, a reply we failed to transcribe and audio that would not decode are three
                different findings, and the run keeps them apart. A metric without the data it needs is shown as not
                reported, never as zero.
              </p>
              <div className="mt-8 rounded-xl border border-line p-5">
                <p className="text-[13px] font-semibold text-text">Not measured by this evaluator</p>
                <ul className="mt-3 flex flex-wrap gap-2">
                  {unmeasuredQualities.map((quality) => (
                    <li
                      key={quality}
                      className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-2.5 py-1 text-[12px] text-text-2"
                    >
                      <CircleSlash aria-hidden="true" className="size-3 text-text-3" />
                      {quality}
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-[13px] leading-relaxed text-text-3">{unmeasuredReason}</p>
              </div>
            </div>
            <ul className="grid content-start gap-3">
              <EvidenceRow
                title="Silence"
                owner="A finding about the bot"
                body="Transcription succeeded and heard no speech. The bot said nothing."
                tone="idle"
              />
              <EvidenceRow
                title="Not transcribed"
                owner="Our failure"
                body="Audio arrived but recognition failed, so what the bot said is unknown. The conversation continues."
                tone="warn"
              />
              <EvidenceRow
                title="Audio invalid"
                owner="Neither side's words"
                body="The audio could not be decoded. The run fails with that reason, not with a verdict about the bot."
                tone="bad"
              />
            </ul>
          </div>
        </section>

        {/* 6. Limits */}
        <section id="limits" aria-labelledby="limits-title" className="border-b border-line bg-bg-soft">
          <div className="mx-auto max-w-6xl px-5 py-20 sm:px-8 lg:py-28">
            <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
              <h2 id="limits-title" className="max-w-2xl text-[clamp(1.9rem,3.6vw,2.75rem)] font-medium leading-[1.08] tracking-[-0.035em]">
                What it does not do yet.
              </h2>
              <p className="font-mono text-[12px] text-text-3">{statusBadge}</p>
            </div>
            <ul className="mt-10 grid gap-4 md:grid-cols-2">
              {limitations.map((limit) => (
                <li key={limit.title} className="flex gap-4 rounded-xl border border-line bg-bg p-6">
                  <PhoneOff aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-text-3" strokeWidth={1.75} />
                  <div>
                    <h3 className="text-[15px] font-semibold">{limit.title}</h3>
                    <p className="mt-2 text-[14px] leading-relaxed text-text-2">{limit.detail.replaceAll("`", "")}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* 7. Docs and close */}
        <section id="docs" aria-labelledby="docs-title">
          <div className="mx-auto max-w-6xl px-5 py-20 sm:px-8 lg:py-28">
            <div className="grid gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
              <div>
                <h2 id="docs-title" className="text-[clamp(1.9rem,3.6vw,2.75rem)] font-medium leading-[1.08] tracking-[-0.035em]">
                  Read the protocol, then run your first test.
                </h2>
                <p className="mt-5 max-w-md text-[16px] leading-relaxed text-text-2">
                  Built for teams shipping voice bots for Indian users: a check before each release, a baseline when you
                  change speech provider, and the turn-by-turn record when a caller complains.
                </p>
                <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                  <Link href="/signup" className={buttonClass("primary", "lg")}>
                    Create an account
                  </Link>
                  <Link href="/login" className={buttonClass("secondary", "lg")}>
                    Sign in
                  </Link>
                </div>
              </div>
              <ul className="grid gap-3 sm:grid-cols-2">
                {docs.map((doc) => (
                  <li key={doc.href}>
                    <a
                      href={doc.href}
                      target="_blank"
                      rel="noreferrer"
                      className="group flex h-full flex-col rounded-xl border border-line p-5 transition-[transform,border-color,box-shadow] duration-200 hover:-translate-y-0.5 hover:border-line-strong hover:shadow-2"
                    >
                      <BookOpen aria-hidden="true" className="size-4 text-text-3" strokeWidth={1.75} />
                      <span className="mt-4 text-[15px] font-semibold text-text">{doc.title}</span>
                      <span className="mt-1.5 text-[14px] leading-relaxed text-text-2">{doc.body}</span>
                      <span className="mt-4 inline-flex items-center gap-1 text-[13px] font-medium text-accent">
                        Read on GitHub
                        <ArrowRight aria-hidden="true" className="size-3.5 transition-transform group-hover:translate-x-0.5" />
                      </span>
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}

function EvidenceRow({
  title,
  owner,
  body,
  tone,
}: {
  title: string;
  owner: string;
  body: string;
  tone: "idle" | "warn" | "bad";
}) {
  const stripe = { idle: "bg-idle", warn: "bg-warn", bad: "bg-bad" }[tone];
  return (
    <li className="relative overflow-hidden rounded-xl border border-line bg-bg p-5 pl-6 shadow-1">
      <span aria-hidden="true" className={cx("absolute inset-y-0 left-0 w-1", stripe)} />
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[15px] font-semibold">{title}</p>
        <p className="font-mono text-[12px] text-text-3">{owner}</p>
      </div>
      <p className="mt-2 text-[14px] leading-relaxed text-text-2">{body}</p>
    </li>
  );
}
