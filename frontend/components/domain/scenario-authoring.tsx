"use client";

/**
 * Create a suite, and add a scenario to one from YAML.
 *
 * Validation runs first, against the real validator (`POST
 * /scenarios/validate`), and its field-addressed errors are shown as the
 * API reported them. Only a document that validated can be submitted, and
 * the server validates it again on create - the button is a convenience,
 * not the check.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";
import type { LibraryScenario, ScenarioValidation, SuiteSummary } from "@/lib/api/types";

const field =
  "mt-1.5 block w-full rounded-md border border-line-strong bg-surface-raised px-3 py-2 text-[13px] text-text";

function message(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

export interface ProjectChoice {
  id: string;
  label: string;
}

export function CreateSuite({ projects }: { projects: ProjectChoice[] }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  return (
    <form
      className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
      onSubmit={async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        setPending(true);
        setError(null);
        try {
          const data = new FormData(form);
          await api.createSuiteIn(String(data.get("name")), String(data.get("project")));
          form.reset();
          router.refresh();
        } catch (cause) {
          setError(message(cause, "The suite could not be created."));
        } finally {
          setPending(false);
        }
      }}
    >
      <label className="block text-[13px] font-medium text-text-muted">
        New suite name
        <input name="name" required maxLength={200} className={field} />
      </label>
      <label className="block text-[13px] font-medium text-text-muted sm:col-span-2">
        In project
        <select name="project" required className={field} defaultValue={projects[0]?.id}>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.label}</option>
          ))}
        </select>
      </label>
      <Button type="submit" tone="primary" size="sm" disabled={pending || projects.length === 0}>
        {pending ? "Creating…" : "Create suite"}
      </Button>
      {error ? <p role="alert" className="text-[12px] text-bad sm:col-span-2">{error}</p> : null}
    </form>
  );
}

export function AddScenario({
  suites,
  library,
}: {
  suites: SuiteSummary[];
  /** The shipped reference scenarios; `null` when the library could not be read. */
  library: LibraryScenario[] | null;
}) {
  const router = useRouter();
  const [yaml, setYaml] = useState("");
  const [picked, setPicked] = useState("");
  const [suiteId, setSuiteId] = useState(suites[0]?.id ?? "");
  const [validation, setValidation] = useState<ScenarioValidation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [created, setCreated] = useState<string | null>(null);

  if (suites.length === 0) {
    return <p className="text-[13px] text-text-muted">Create a suite first; a scenario always belongs to one.</p>;
  }

  async function act(action: () => Promise<void>) {
    setPending(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      setError(message(cause, "The request failed."));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="grid gap-3">
      <label className="block text-[13px] font-medium text-text-muted">
        Suite
        <select value={suiteId} onChange={(e) => setSuiteId(e.target.value)} className={field}>
          {suites.map((suite) => (
            <option key={suite.id} value={suite.id}>{suite.name}</option>
          ))}
        </select>
      </label>
      <label className="block text-[13px] font-medium text-text-muted">
        Start from a reference scenario
        <select
          value={picked}
          disabled={!library || library.length === 0}
          onChange={(e) => {
            const entry = library?.find((item) => item.key === e.target.value);
            setPicked(e.target.value);
            if (entry) {
              setYaml(entry.yaml);
              setValidation(null);
              setCreated(null);
            }
          }}
          className={field}
        >
          <option value="">
            {library === null ? "The reference library could not be loaded" : "Write your own, or choose one…"}
          </option>
          {(library ?? []).map((item) => (
            <option key={item.key} value={item.key}>
              {item.name} ({item.language})
            </option>
          ))}
        </select>
        {picked ? (
          <span className="mt-1 block text-[12px] font-normal leading-relaxed text-text-dim">
            {library?.find((item) => item.key === picked)?.objective} Edit it below - the
            language, persona, facts and audio conditions are all in the YAML - then
            validate and add it.
          </span>
        ) : null}
      </label>
      <label className="block text-[13px] font-medium text-text-muted">
        Scenario YAML (see docs/SCENARIO_FORMAT.md)
        <textarea
          value={yaml}
          onChange={(e) => {
            setYaml(e.target.value);
            setValidation(null);
            setCreated(null);
          }}
          rows={12}
          spellCheck={false}
          className={`${field} font-mono`}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          disabled={pending || !yaml.trim()}
          onClick={() => act(async () => setValidation(await api.validateScenario(yaml)))}
        >
          Validate
        </Button>
        <Button
          tone="primary"
          size="sm"
          disabled={pending || !validation?.valid}
          onClick={() =>
            act(async () => {
              const scenario = await api.createScenario(suiteId, yaml);
              setCreated(scenario.name);
              setYaml("");
              setPicked("");
              setValidation(null);
              router.refresh();
            })
          }
        >
          Add to suite
        </Button>
      </div>
      {validation !== null ? (
        validation.valid ? (
          <p role="status" className="text-[13px] text-ok">Valid. It can be added.</p>
        ) : (
          <ul role="alert" className="space-y-1 text-[12px] text-bad">
            {validation.errors.map((e, i) => (
              <li key={`${e.field}-${i}`}>
                <span className="font-mono">{e.field}</span>: {e.message}
              </li>
            ))}
          </ul>
        )
      ) : null}
      {created ? <p role="status" className="text-[13px] text-ok">Added &ldquo;{created}&rdquo;.</p> : null}
      {error ? <p role="alert" className="text-[12px] text-bad">{error}</p> : null}
    </div>
  );
}
