/**
 * Formatting for values that came from a measurement.
 *
 * The rule throughout: a value that was not measured is never formatted into
 * something that looks like it was. Every helper here takes `null` and
 * returns `null`, leaving the component to render "not reported" rather than
 * a zero, a dash, or a rounded nothing.
 */

/** Seconds, at the precision the measurement supports. */
export function formatSeconds(value: number | null | undefined): string | null {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  if (value < 1) return `${Math.round(value * 1000)} ms`;
  if (value < 60) return `${value.toFixed(value < 10 ? 2 : 1)} s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

/** Milliseconds, as the stage timeline reports them. */
export function formatMs(value: number | null | undefined): string | null {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  if (value >= 10) return `${Math.round(value)} ms`;
  return `${value.toFixed(1)} ms`;
}

export function formatBytes(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatHz(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  return value >= 1000 ? `${(value / 1000).toFixed(value % 1000 === 0 ? 0 : 1)} kHz` : `${value} Hz`;
}

/**
 * An absolute timestamp, in the viewer's locale.
 *
 * Absolute rather than relative: "3 minutes ago" is friendlier and useless
 * in an evidence trail, where the question is usually whether two runs
 * happened before or after a change.
 */
export function formatTimestamp(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

/** Short form for a dense table column. */
export function formatTimestampShort(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** `heavy_background_noise` reads as "Heavy background noise". */
export function humanise(value: string | null | undefined): string | null {
  if (!value) return null;
  const spaced = value.replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** The first eight characters of a UUID, for a dense column. */
export function shortId(value: string): string {
  return value.slice(0, 8);
}

/**
 * The `lang` attribute for a stretch of text in a catalogue language.
 *
 * BhashaBench tags are already BCP 47 (`hi-IN`, `ta-IN`), so they can be
 * used directly. This matters more here than in most products: a screen
 * reader handed Devanagari inside `lang="en"` pronounces it with English
 * phonetics, which is worse than silence.
 */
export function langAttr(tag: string | null | undefined): string | undefined {
  if (!tag) return undefined;
  return /^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$/.test(tag) ? tag : undefined;
}
