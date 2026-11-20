// The public site's phase table against the repository's own.
//
// lib/content.ts once said "Phase 8 of 15" for a week after Phase 14 closed:
// the number was typed in by hand and nothing compared it with anything.
// README.md's status table is the authority (CLAUDE.md and the roadmap must
// agree with it), so this reads that table and fails when the landing page
// says something different.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { completedPhases, phases, statusBadge, totalPhases } from "../lib/content.ts";

const README = new URL("../../README.md", import.meta.url);

/** Rows of the form `| 7 | Audio degradation engine | ✅ Complete (...) |`. */
function readmePhases() {
  const rows = new Map();
  for (const line of readFileSync(README, "utf8").split("\n")) {
    const match = /^\| (\d+) \| [^|]+ \| (✅|🟡|⬜|❌)/u.exec(line);
    if (match) rows.set(Number(match[1]), match[2]);
  }
  return rows;
}

describe("the landing page's phase table", () => {
  const readme = readmePhases();

  it("finds the README table", () => {
    assert.ok(readme.size >= 15, `found ${readme.size} phase rows in README.md`);
  });

  it("lists phases 1 to 15, once each, in order", () => {
    assert.deepEqual(
      phases.map((p) => p.number),
      Array.from({ length: 15 }, (_, i) => i + 1),
    );
  });

  it("agrees with README.md on every phase's status", () => {
    const expected = { "✅": "built", "🟡": "partial" };
    for (const phase of phases) {
      const mark = readme.get(phase.number);
      assert.ok(mark, `phase ${phase.number} is missing from README.md`);
      assert.equal(
        phase.status,
        expected[mark] ?? "planned",
        `phase ${phase.number} (${phase.title}) is ${phase.status} on the site and ${mark} in README.md`,
      );
    }
  });

  it("derives the badge from the table rather than a typed number", () => {
    assert.equal(totalPhases, 15);
    assert.ok(statusBadge.startsWith(`${completedPhases} of 15 phases complete`), statusBadge);
    assert.match(statusBadge, /no telephone call placed/);
  });
});

describe("the landing page's language list", () => {
  it("matches backend/app/core/languages.py, the catalogue's single source of truth", async () => {
    const { languages } = await import("../lib/content.ts");
    const source = readFileSync(new URL("../../backend/app/core/languages.py", import.meta.url), "utf8");
    const rows = [...source.matchAll(/Language\("([^"]+)", "([^"]+)", "([^"]+)", "([^"]+)", "[^"]+"\)/g)].map(
      (m) => ({ code: m[1], name: m[2], endonym: m[3], script: m[4] }),
    );
    assert.ok(rows.length >= 13, `found ${rows.length} catalogue rows`);
    assert.deepEqual(
      languages.map(({ code, name, endonym, script }) => ({ code, name, endonym, script })),
      rows,
    );
  });
});
