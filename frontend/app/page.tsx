import { CapabilityCard } from "@/components/capability-card";
import { RoadmapList } from "@/components/roadmap-list";
import { Section } from "@/components/section";
import { StatusPill } from "@/components/status-pill";
import {
  apiBaseUrl,
  capabilities,
  currentPhase,
  endpoints,
  site,
  totalPhases,
} from "@/lib/content";

export default function HomePage() {
  return (
    <div className="mx-auto max-w-6xl px-6">
      <Hero />

      <Section
        id="test-suite"
        eyebrow="Test suite"
        title="What BhashaBench will test"
        intro="A voice bot that passes a quiet demo often fails a real Indian phone call. These are the capabilities the platform is being built to exercise — none of them are implemented yet, and each card names the phase that delivers it."
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {capabilities.map((capability) => (
            <CapabilityCard key={capability.title} capability={capability} />
          ))}
        </div>
      </Section>

      <Section
        id="api"
        eyebrow="API"
        title="Endpoints available today"
        intro="The Phase 1 backend is a running FastAPI service. These three endpoints work; everything else returns 404 until a later phase adds it."
      >
        <EndpointTable />
      </Section>

      <Section
        id="roadmap"
        eyebrow="Roadmap"
        title="Fifteen phases"
        intro="Each phase ends with working code, passing tests and updated documentation. A phase is not started until the previous one is reviewed."
      >
        <RoadmapList />
      </Section>
    </div>
  );
}

function Hero() {
  return (
    <section id="overview" aria-labelledby="overview-heading" className="scroll-mt-20 py-16 sm:py-24">
      <StatusPill
        status="partial"
        label={`Phase ${currentPhase} of ${totalPhases} — no calls placed yet`}
      />

      <h1
        id="overview-heading"
        className="mt-6 max-w-3xl text-4xl font-semibold leading-[1.1] tracking-tight text-text-primary sm:text-5xl lg:text-6xl"
      >
        {site.tagline}
      </h1>

      <p className="mt-6 max-w-2xl text-lg leading-relaxed text-text-secondary">
        {site.name} is an automated testing and benchmarking platform for
        Indian-language voice bots — simulated callers, realistic audio
        degradation and automated conversation scoring.
      </p>

      <div className="mt-8 flex flex-wrap items-center gap-3">
        <a
          href={`${apiBaseUrl}/docs`}
          target="_blank"
          rel="noreferrer"
          className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-surface-base transition-colors hover:bg-accent-strong"
        >
          Open API docs
        </a>
        <a
          href={site.repository}
          target="_blank"
          rel="noreferrer"
          className="rounded-lg border border-border-strong px-4 py-2.5 text-sm font-medium text-text-secondary transition-colors hover:border-accent/50 hover:text-text-primary"
        >
          View source
        </a>
      </div>

      <p className="mt-6 max-w-2xl text-sm leading-relaxed text-text-tertiary">
        This is the foundation release. The application skeleton,
        configuration, health endpoints and container setup are in place. No
        calls are placed, no speech is processed and no scores are produced
        yet.
      </p>
    </section>
  );
}

function EndpointTable() {
  return (
    <div className="overflow-x-auto rounded-xl border border-border-subtle">
      <table className="w-full min-w-[34rem] border-collapse text-left text-sm">
        <thead>
          <tr className="bg-surface-overlay text-xs uppercase tracking-wider text-text-tertiary">
            <th scope="col" className="px-4 py-2.5 font-medium">
              Method
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              Path
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              Returns
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {endpoints.map((endpoint) => (
            <tr
              key={endpoint.path}
              className="border-t border-border-subtle bg-surface-raised"
            >
              <td className="px-4 py-3 font-mono text-xs text-status-live">
                {endpoint.method}
              </td>
              <td className="px-4 py-3 font-mono text-xs text-text-primary">
                {endpoint.path}
              </td>
              <td className="px-4 py-3 text-text-secondary">
                {endpoint.summary}
              </td>
              <td className="px-4 py-3">
                <StatusPill status="live" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
