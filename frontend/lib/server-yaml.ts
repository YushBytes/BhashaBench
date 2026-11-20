/**
 * YAML for the server, which reads it with PyYAML's `safe_load` - YAML 1.1.
 *
 * The `yaml` package writes YAML 1.2 by default, where `2026-10-28`, `yes`,
 * `no`, `on` and `off` are plain strings and need no quotes. YAML 1.1 reads
 * the same bare words as a date and as booleans, so a scenario built from
 * the shipped `english_insurance_claim` came back with
 * `known_facts.incident_date` "not a valid string" and could not be created.
 * Writing in 1.1 mode quotes every string 1.1 would reinterpret.
 */

import { stringify } from "yaml";

export function toServerYaml(value: unknown): string {
  return stringify(value, { lineWidth: 100, version: "1.1" });
}
