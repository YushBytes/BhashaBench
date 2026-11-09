"use client";

/**
 * Playback and waveform for one stored artefact.
 *
 * **The waveform is drawn from the audio, or not at all.** The bytes are
 * fetched, decoded with the Web Audio API and reduced to per-pixel peaks.
 * There is no synthetic fallback: if decoding fails the component says the
 * waveform could not be drawn and still offers playback. A plausible-looking
 * generated waveform would be a picture of a sound that does not exist,
 * which is the exact class of thing this product may not show.
 *
 * **Nothing is fetched until asked.** A run with twenty turns has forty
 * artefacts; decoding all of them on page load would download megabytes to
 * draw thumbnails nobody looked at. The peaks are computed on first
 * expansion and kept.
 */

import { useCallback, useEffect, useId, useRef, useState } from "react";

import { cx } from "@/components/ui/primitives";
import { formatBytes, formatHz, formatSeconds } from "@/lib/format";
import type { Artefact } from "@/lib/api/types";
import { artefactAudioUrl } from "@/lib/api/client";

type Decode = "idle" | "loading" | "ready" | "undecodable" | "unreachable";

/** Reduce samples to one min/max pair per bar. */
function peaksFrom(buffer: AudioBuffer, bars: number): number[] {
  const data = buffer.getChannelData(0);
  const block = Math.max(1, Math.floor(data.length / bars));
  const peaks: number[] = [];
  for (let index = 0; index < bars; index += 1) {
    const start = index * block;
    let peak = 0;
    for (let offset = 0; offset < block && start + offset < data.length; offset += 1) {
      const value = Math.abs(data[start + offset]);
      if (value > peak) peak = value;
    }
    peaks.push(peak);
  }
  // Normalise against the loudest bar so a quiet utterance is still legible.
  // The scale is therefore relative within one artefact and not comparable
  // between two - which is why no amplitude figure is printed beside it.
  const loudest = Math.max(...peaks, 0.0001);
  return peaks.map((peak) => peak / loudest);
}

function Waveform({
  peaks,
  progress,
  tone,
}: {
  peaks: number[];
  progress: number;
  tone: "caller" | "bot";
}) {
  const colour = tone === "caller" ? "var(--accent)" : "var(--accent-alt)";
  return (
    <svg
      viewBox={`0 0 ${peaks.length} 40`}
      preserveAspectRatio="none"
      className="h-10 w-full"
      aria-hidden="true"
    >
      {peaks.map((peak, index) => {
        const height = Math.max(1.5, peak * 36);
        const played = index / peaks.length <= progress;
        return (
          <rect
            key={index}
            x={index + 0.15}
            y={(40 - height) / 2}
            width={0.7}
            height={height}
            rx={0.35}
            fill={played ? colour : "var(--line-strong)"}
          />
        );
      })}
    </svg>
  );
}

export function AudioArtefactPlayer({
  runId,
  artefact,
  tone,
}: {
  runId: string;
  artefact: Artefact;
  tone: "caller" | "bot";
}) {
  const url = artefactAudioUrl(runId, artefact.turn_index, artefact.variant);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [state, setState] = useState<Decode>("idle");
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const titleId = useId();

  const analyse = useCallback(async () => {
    if (state !== "idle") return;
    setState("loading");
    try {
      const response = await fetch(url);
      if (!response.ok) {
        setState("unreachable");
        return;
      }
      const bytes = await response.arrayBuffer();
      const Ctor =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext })
          .webkitAudioContext;
      if (!Ctor) {
        setState("undecodable");
        return;
      }
      const context = new Ctor();
      try {
        const decoded = await context.decodeAudioData(bytes);
        setPeaks(peaksFrom(decoded, 160));
        setState("ready");
      } finally {
        void context.close();
      }
    } catch {
      // A container the browser cannot decode (mulaw, raw) is a normal
      // outcome here, not a bug. Playback may still work.
      setState("undecodable");
    }
  }, [state, url]);

  // Decode when the turn scrolls into view, not on mount. Subscribing to an
  // observer is the effect's proper job, and it means a twenty-turn run does
  // not fetch forty artefacts to draw thumbnails nobody scrolled to.
  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          void analyse();
          observer.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [analyse]);

  function toggle() {
    const element = audioRef.current;
    if (!element) return;
    if (element.paused) {
      void element.play();
    } else {
      element.pause();
    }
  }

  const duration = formatSeconds(artefact.duration_seconds);
  const rate = formatHz(artefact.sample_rate_hz);
  const size = formatBytes(artefact.size_bytes);

  return (
    <div ref={rootRef} className="rounded-md border border-line bg-surface-inset p-2.5">
      <div className="flex items-center gap-2.5">
        <button
          type="button"
          onClick={toggle}
          aria-describedby={titleId}
          className={cx(
            "flex size-9 shrink-0 items-center justify-center rounded-full border transition-colors",
            "border-line-strong bg-surface-raised text-text hover:border-accent hover:text-accent",
          )}
        >
          <span className="sr-only">{playing ? "Pause" : "Play"} this audio</span>
          {playing ? (
            <svg viewBox="0 0 16 16" className="size-3.5" aria-hidden="true" fill="currentColor">
              <rect x="3.5" y="2.5" width="3" height="11" rx="1" />
              <rect x="9.5" y="2.5" width="3" height="11" rx="1" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" className="size-3.5" aria-hidden="true" fill="currentColor">
              <path d="M4.5 2.8a1 1 0 0 1 1.52-.85l7 5.2a1 1 0 0 1 0 1.7l-7 5.2A1 1 0 0 1 4.5 13.2Z" />
            </svg>
          )}
        </button>

        <div className="min-w-0 flex-1">
          {state === "ready" && peaks ? (
            <Waveform peaks={peaks} progress={progress} tone={tone} />
          ) : state === "idle" || state === "loading" ? (
            // `idle` means the artefact has not scrolled into view yet, which
            // is not a failure and must not be reported as one.
            <div className="bb-skeleton h-10 w-full" />
          ) : (
            <p className="py-2 text-[12px] text-text-muted">
              {state === "unreachable"
                ? "Audio could not be fetched — this environment may not be serving stored artefacts."
                : "Waveform unavailable: this browser cannot decode the container. Playback may still work."}
            </p>
          )}
        </div>
      </div>

      <audio
        ref={audioRef}
        src={url}
        preload="metadata"
        controls
        className="mt-2 h-8 w-full"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setProgress(0);
        }}
        onTimeUpdate={(event) => {
          const element = event.currentTarget;
          if (element.duration > 0) setProgress(element.currentTime / element.duration);
        }}
      >
        <track kind="captions" />
      </audio>

      <p id={titleId} className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[11px] text-text-muted">
        <span>{artefact.variant ?? "stored"}</span>
        {duration ? <span>{duration}</span> : null}
        {rate ? <span>{rate}</span> : null}
        {artefact.channels ? <span>{artefact.channels} ch</span> : null}
        {size ? <span>{size}</span> : null}
      </p>
    </div>
  );
}
