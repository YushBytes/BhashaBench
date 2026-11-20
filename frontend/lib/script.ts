/**
 * Split text into runs of one writing system (ISO 15924), word by word.
 *
 * The same idea as the backend's `script_segments`, used on the public page
 * to show what the evaluator would see in a real line of text. Script, not
 * language: romanised Hindi is Latn, and Hindi and Marathi share Deva. A word
 * with no letters (digits, punctuation) joins the run it sits in.
 */

const RANGES: [string, number, number][] = [
  ["Deva", 0x0900, 0x097f],
  ["Beng", 0x0980, 0x09ff],
  ["Guru", 0x0a00, 0x0a7f],
  ["Gujr", 0x0a80, 0x0aff],
  ["Orya", 0x0b00, 0x0b7f],
  ["Taml", 0x0b80, 0x0bff],
  ["Telu", 0x0c00, 0x0c7f],
  ["Knda", 0x0c80, 0x0cff],
  ["Mlym", 0x0d00, 0x0d7f],
  ["Arab", 0x0600, 0x06ff],
];

function scriptOfChar(code: number): string | null {
  for (const [name, low, high] of RANGES) if (code >= low && code <= high) return name;
  if ((code >= 0x41 && code <= 0x5a) || (code >= 0x61 && code <= 0x7a)) return "Latn";
  return null;
}

/** The dominant script of one word, or null when it has no letters. */
export function scriptOfWord(word: string): string | null {
  const counts = new Map<string, number>();
  for (const char of word) {
    const script = scriptOfChar(char.codePointAt(0) ?? 0);
    if (script) counts.set(script, (counts.get(script) ?? 0) + 1);
  }
  let best: string | null = null;
  let most = 0;
  for (const [script, count] of counts) if (count > most) [best, most] = [script, count];
  return best;
}

export interface ScriptRun {
  script: string;
  text: string;
  words: number;
}

export function scriptRuns(text: string): ScriptRun[] {
  const runs: ScriptRun[] = [];
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const script = scriptOfWord(word);
    const last = runs.at(-1);
    if (last && (script === null || script === last.script)) {
      last.text += ` ${word}`;
      if (script) last.words += 1;
    } else if (script === null) {
      // Leading punctuation or digits with no run yet: start an unknown run.
      runs.push({ script: "Zyyy", text: word, words: 0 });
    } else if (last && last.script === "Zyyy") {
      last.script = script;
      last.text += ` ${word}`;
      last.words += 1;
    } else {
      runs.push({ script, text: word, words: 1 });
    }
  }
  return runs;
}
