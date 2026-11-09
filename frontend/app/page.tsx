import Link from "next/link";

import { SiteFooter, SiteHeader } from "@/components/marketing/chrome";
import { PipelineDiagram } from "@/components/marketing/pipeline-diagram";
import { Badge } from "@/components/ui/status";
import { buttonClass, cx } from "@/components/ui/primitives";
import {
  capabilities,
  currentPhase,
  limitations,
  phases,
  site,
  totalPhases,
  workflow,
} from "@/lib/content";

/**
 * The public site.
 *
 * A Persuade surface: it has to make a stranger understand what this
 * instrument measures within one screen. What it may not do is overstate —
 * so the limitations have a section of their own rather than a footnote,
 * and the status table marks two of the eight delivered phases partial.
 */

const STATUS_TONE = {
  built: "ok",
  partial: "warn",
  planned: "idle",
} as const;

const STATUS_LABEL = {
  built: "Built",
  partial: "Partial",
  planned: "Planned",
} as const;

export default function HomePage() {
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only rounded-md bg-accent px-3 py-2 text-sm font-semibold text-bg focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50"
      >
        Skip to content
      </a>

      <SiteHeader />

      <main id="main" className="flex-1">
        <Hero />
        <Workflow />
        <Capabilities />
        <Conditions />
        <Limitations />
        <Status />
        <Closing />
      </main>

      <SiteFooter />
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function Hero() {
  return (
    <section className="border-b border-line">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:px-6 sm:py-20 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] lg:items-center lg:gap-14">
        <div>
          <Badge tone="warn">
            Phase {currentPhase} of {totalPhases} · no telephone call placed yet
          </Badge>

          <h1 className="mt-5 text-[2.25rem] font-semibold leading-[1.08] tracking-[-0.02em] text-text sm:text-5xl lg:text-[3.5rem]">
            Does your voice AI actually understand India?
          </h1>

          <p className="mt-5 max-w-xl text-[17px] leading-relaxed text-text-dim">
            {site.description}
          </p>

          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Link href="/app" className={buttonClass("primary", "md")}>
              Explore the test bench
            </Link>
            <a href="#workflow" className={buttonClass("default", "md")}>
              See how it works
            </a>
          </div>

          <p className="mt-6 max-w-xl text-[13px] leading-relaxed text-text-muted">
            A bot that passes a quiet demo in a studio fails a real call from a
            market in Coimbatore. BhashaBench drives that call deliberately:
            thirteen catalogue languages, measured acoustic degradation, and an
            evidence trail for every turn.
          </p>
        </div>

        <PipelineDiagram />
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */

function SectionShell({
  id,
  title,
  intro,
  children,
  bordered = true,
}: {
  id: string;
  title: string;
  intro?: string;
  children: React.ReactNode;
  bordered?: boolean;
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-heading`}
      className={cx("scroll-mt-20", bordered && "border-b border-line")}
    >
      <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-18">
        <h2
          id={`${id}-heading`}
          className="text-2xl font-semibold tracking-[-0.015em] text-text sm:text-[28px]"
        >
          {title}
        </h2>
        {intro ? (
          <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-text-dim">
            {intro}
          </p>
        ) : null}
        <div className="mt-8">{children}</div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */

function Workflow() {
  return (
    <SectionShell
      id="workflow"
      title="What a test actually does"
      intro="Seven steps, in this order. Each one is a stage the pipeline executes and times."
    >
      <ol className="grid gap-x-10 gap-y-0 md:grid-cols-2">
        {workflow.map((item, index) => (
          <li
            key={item.step}
            className="grid grid-cols-[2rem_minmax(0,1fr)] gap-x-4 border-t border-line py-5 first:border-t-0 md:first:border-t md:[&:nth-child(2)]:border-t-0"
          >
            {/* The number is the sequence, which is the information here:
                these steps depend on each other in this order. */}
            <span className="font-mono text-[13px] tabular text-accent">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-medium text-text">{item.step}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-text-dim">
                {item.detail}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </SectionShell>
  );
}

/* -------------------------------------------------------------------------- */

function Capabilities() {
  return (
    <SectionShell
      id="capabilities"
      title="What is built"
      intro="Each entry names the phase that delivered it and carries its real status. Two of these are marked partial, and the reasons are in the next section."
    >
      <ul className="divide-y divide-line border-y border-line">
        {capabilities.map((capability) => (
          <li
            key={capability.title}
            className="grid gap-x-8 gap-y-2 py-5 md:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]"
          >
            <div className="flex flex-wrap items-start gap-2">
              <h3 className="text-[15px] font-medium text-text">{capability.title}</h3>
              <Badge tone={STATUS_TONE[capability.status]}>
                {STATUS_LABEL[capability.status]}
              </Badge>
            </div>
            <p className="text-[13px] leading-relaxed text-text-dim">
              {capability.summary}
            </p>
          </li>
        ))}
      </ul>
    </SectionShell>
  );
}

/* -------------------------------------------------------------------------- */

/**
 * The acoustic conditions section.
 *
 * Deliberately not a pair of drawn waveforms: a waveform that did not come
 * from a file is a picture of a sound that does not exist. What is shown
 * instead is the thing that is actually unusual here — that the noise is
 * scaled from each utterance's own signal, and the achieved ratio is
 * asserted rather than assumed.
 */
function Conditions() {
  const profiles = [
    ["clean", "No degradation — a deliberate condition, not a skipped stage"],
    ["telephony_bandwidth", "Band-limited to what a phone line carries"],
    ["light_background_noise", "A quiet room with something happening in it"],
    ["moderate_background_noise", "A street, a shop, a bus stop"],
    ["heavy_background_noise", "The hardest condition this engine simulates"],
  ] as const;

  return (
    <SectionShell
      id="conditions"
      title="Audio that behaves like a real call"
      intro="A test under studio conditions tells you how a bot performs under studio conditions. These are the environments a run can be executed in."
    >
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <ul className="divide-y divide-line rounded-lg border border-line">
          {profiles.map(([name, blurb]) => (
            <li key={name} className="flex flex-col gap-1 px-4 py-3">
              <span className="font-mono text-[13px] text-accent">{name}</span>
              <span className="text-[13px] leading-relaxed text-text-dim">{blurb}</span>
            </li>
          ))}
        </ul>

        <div className="space-y-4">
          <Point title="Noise is scaled to the signal, not added at a fixed level">
            Each utterance&rsquo;s own RMS sets the noise floor, so a stated
            signal-to-noise ratio means the same thing for a loud speaker and a
            quiet one. The achieved ratio is then measured and asserted to
            better than 0.5 dB rather than trusted.
          </Point>
          <Point title="A seed is required for anything stochastic">
            Runs reproduce exactly. An artefact nobody can reproduce is not
            evidence, so the engine refuses to randomise without one.
          </Point>
          <Point title="The original always survives">
            Degradation returns new bytes and overwrites nothing. Both files
            are kept and the processed one records what it came from, so the
            pair stays comparable afterwards.
          </Point>
          <Point title="These are simulated conditions, not field recordings">
            The transformations approximate a noisy line. They are not
            recordings of one, and nothing in this product claims otherwise.
          </Point>
        </div>
      </div>
    </SectionShell>
  );
}

function Point({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-l-[1px] border-accent-line pl-4">
      <h3 className="text-[14px] font-medium text-text">{title}</h3>
      <p className="mt-1 text-[13px] leading-relaxed text-text-dim">{children}</p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function Limitations() {
  return (
    <SectionShell
      id="limitations"
      title="What this does not do yet"
      intro="An instrument that overstates its reach is worse than no instrument. These are the four things people most often assume are working here."
    >
      <ul className="grid gap-4 md:grid-cols-2">
        {limitations.map((item) => (
          <li
            key={item.title}
            className="rounded-lg border border-line bg-surface p-4"
          >
            <div className="flex items-start gap-2">
              <span
                aria-hidden="true"
                className="mt-[7px] inline-block size-1.5 shrink-0 rounded-full bg-warn"
              />
              <div className="min-w-0">
                <h3 className="text-[14px] font-medium text-text">{item.title}</h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-text-dim">
                  {item.detail}
                </p>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </SectionShell>
  );
}

/* -------------------------------------------------------------------------- */

function Status() {
  return (
    <SectionShell
      id="status"
      title="Fifteen phases"
      intro="Each ends with working code, passing tests and updated documentation. A phase does not start until the previous one is reviewed."
    >
      <ol className="overflow-hidden rounded-lg border border-line">
        {phases.map((phase, index) => (
          <li
            key={phase.number}
            className={cx(
              "grid grid-cols-[2.25rem_minmax(0,1fr)_auto] items-start gap-x-3 px-4 py-3 sm:gap-x-4",
              index % 2 === 0 ? "bg-surface" : "bg-bg",
            )}
          >
            <span className="font-mono text-[12px] tabular text-text-muted">
              {String(phase.number).padStart(2, "0")}
            </span>
            <div className="min-w-0">
              <span
                className={cx(
                  "text-[14px]",
                  phase.status === "planned" ? "text-text-dim" : "font-medium text-text",
                )}
              >
                {phase.title}
              </span>
              {phase.note ? (
                <p className="mt-1 text-[12px] leading-relaxed text-text-muted">
                  {phase.note}
                </p>
              ) : null}
            </div>
            <Badge tone={STATUS_TONE[phase.status]}>{STATUS_LABEL[phase.status]}</Badge>
          </li>
        ))}
      </ol>
    </SectionShell>
  );
}

/* -------------------------------------------------------------------------- */

function Closing() {
  return (
    <section className="scroll-mt-20">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
        <h2 className="max-w-2xl text-2xl font-semibold tracking-[-0.015em] text-text sm:text-[28px]">
          Open the workspace and look at the evidence yourself.
        </h2>
        <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-text-dim">
          Every run keeps its audio, its stage timings and its caller state
          transitions. Nothing is summarised into a score you would have to
          take on trust.
        </p>
        <div className="mt-7 flex flex-wrap items-center gap-3">
          <Link href="/app" className={buttonClass("primary", "md")}>
            Open the workspace
          </Link>
          <a
            href={site.repository}
            target="_blank"
            rel="noreferrer"
            className={buttonClass("default", "md")}
          >
            Read the source
          </a>
        </div>
      </div>
    </section>
  );
}
