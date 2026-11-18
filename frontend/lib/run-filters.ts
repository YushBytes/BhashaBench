/**
 * The run history's filter vocabularies.
 *
 * Each value is sent as a query parameter to `GET /api/v1/test-runs`, which
 * validates it against a backend enum and answers 422 for anything else, so
 * the page shows "could not be loaded" instead of a filtered list.
 * "Created" once did exactly that: the persisted status is `pending`;
 * `created` is the pipeline's finer-grained status, which the filter does
 * not take. `tests/run-filters.test.mjs` reads the backend enums and fails
 * on any value they do not contain.
 */

/** `RunStatus` (backend/app/models/test_run.py): the persisted lifecycle. */
export const RUN_STATUSES = [
  ["pending", "Pending"],
  ["running", "Running"],
  ["completed", "Completed"],
  ["failed", "Failed"],
  ["cancelled", "Cancelled"],
] as const;

/** `ExecutionMode` (backend/app/pipeline/modes.py), creatable modes only. */
export const RUN_MODES = [
  ["offline_simulation", "Offline simulation"],
  ["audio_fixture_test", "Fixture test"],
  ["text_bot_test", "Text bot"],
  ["external_bot_test", "External voice bot"],
] as const;

/** `RunOutcome` (backend/app/pipeline/modes.py). */
export const RUN_OUTCOMES = [
  ["goal_achieved", "Goal achieved"],
  ["bot_refused", "Bot refused"],
  ["bot_unintelligible", "Bot unintelligible"],
  ["no_progress", "No progress"],
  ["turn_budget_exhausted", "Budget exhausted"],
  ["provider_error", "Provider error"],
  ["audio_validation_failed", "Audio invalid"],
  ["external_bot_unavailable", "Bot unavailable"],
  ["bot_protocol_error", "Bot protocol error"],
  ["bot_ended_session", "Bot ended session"],
  ["cancelled", "Cancelled"],
  ["abandoned", "Abandoned"],
] as const;
