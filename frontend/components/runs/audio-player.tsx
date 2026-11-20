"use client";

/**
 * Playback and waveform for one stored artefact.
 *
 * **The waveform is drawn from the audio, or not at all.** The bytes are
 * fetched, decoded with the Web Audio API and reduced to per-bar peaks.
 * There is no synthetic fallback: if decoding fails the component says so
 * and still offers playback. A generated waveform would be a picture of a
 * sound that does not exist.
 *
 * **Nothing is fetched until it scrolls into view.** A twenty-turn run has
 * forty artefacts; decoding all of them on load would download megabytes to
 * draw thumbnails nobody looked at.
 *
 * Amplitude is normalised within one artefact, so two waveforms are not
 * comparable by height - which is why no amplitude figure is printed. Click
 * or use the arrow keys on the waveform to seek.
 */

import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { Pause, Play } from "lucide-react";

import { cx } from "@/components/ui/primitives";
import { artefactAudioUrl } from "@/lib/api/client";
import type { Artefact } from "@/lib/api/types";
import { formatBytes, formatHz, formatSeconds } from "@/lib/format";

type Decode = "idle" | "loading" | "ready" | "undecodable" | "unreachable";

function peaksFrom(buffer: AudioBuffer, bars: number): number[] {
  const data = buffer.getChannelData(0);
  const block = Math.max(1, Math.floor(data.length / bars));
  const peaks: number[] = [];
  for (let i = 0; i < bars; i += 1) {
    let peak = 0;
    for (let j = 0; j < block && i * block + j < data.length; j += 1) {
      const v = Math.abs(data[i * block + j]);
      if (v > peak) peak = v;
    }
    peaks.push(peak);
  }
  const loudest = Math.max(...peaks, 0.0001);
  return peaks.map((p) => p / loudest);
}

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function AudioPlayer({ src, label, meta }: { src: string; label: string; meta?: string[] }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [state, setState] = useState<Decode>("idle");
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const analyse = useCallback(async () => {
    setState("loading");
    try {
      const response = await fetch(src);
      if (!response.ok) {
        setState("unreachable");
        return;
      }
      const bytes = await response.arrayBuffer();
      const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) {
        setState("undecodable");
        return;
      }
      const context = new Ctor();
      try {
        const decoded = await context.decodeAudioData(bytes);
        setPeaks(peaksFrom(decoded, 120));
        setState("ready");
      } finally {
        void context.close();
      }
    } catch {
      // A container the browser cannot decode is a normal outcome, not a bug.
      setState("undecodable");
    }
  }, [src]);

  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
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
    const el = audioRef.current;
    if (!el) return;
    if (el.paused) void el.play();
    else el.pause();
  }

  function seekTo(fraction: number) {
    const el = audioRef.current;
    if (!el || !Number.isFinite(el.duration) || el.duration <= 0) return;
    el.currentTime = Math.min(Math.max(fraction, 0), 1) * el.duration;
  }

  function onClick(event: MouseEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    seekTo((event.clientX - rect.left) / rect.width);
  }

  function onKey(event: KeyboardEvent<HTMLDivElement>) {
    const el = audioRef.current;
    if (!el || !duration) return;
    if (event.key === "ArrowRight") el.currentTime = Math.min(duration, el.currentTime + 1);
    else if (event.key === "ArrowLeft") el.currentTime = Math.max(0, el.currentTime - 1);
    else if (event.key === " " || event.key === "Enter") toggle();
    else return;
    event.preventDefault();
  }

  const progress = duration > 0 ? time / duration : 0;

  return (
    <div ref={rootRef} className="rounded-md border border-line bg-bg-soft p-2.5">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={toggle}
          className="flex size-9 shrink-0 items-center justify-center rounded-full bg-text text-bg transition-transform hover:scale-105 active:scale-95"
        >
          {playing ? <Pause aria-hidden="true" className="size-3.5" fill="currentColor" /> : <Play aria-hidden="true" className="ml-0.5 size-3.5" fill="currentColor" />}
          <span className="sr-only">
            {playing ? "Pause" : "Play"} {label}
          </span>
        </button>
        <div className="min-w-0 flex-1">
          {state === "ready" && peaks ? (
            <div
              role="slider"
              tabIndex={0}
              aria-label={`Seek in ${label}`}
              aria-valuemin={0}
              aria-valuemax={Math.round(duration)}
              aria-valuenow={Math.round(time)}
              aria-valuetext={`${clock(time)} of ${clock(duration)}`}
              onClick={onClick}
              onKeyDown={onKey}
              className="flex h-9 cursor-pointer items-center gap-px"
            >
              {peaks.map((peak, i) => (
                <span
                  key={i}
                  aria-hidden="true"
                  className={cx("w-full min-w-px flex-1 rounded-full", i / peaks.length <= progress && progress > 0 ? "bg-accent" : "bg-line-strong")}
                  style={{ height: `${Math.max(8, peak * 100)}%` }}
                />
              ))}
            </div>
          ) : state === "idle" || state === "loading" ? (
            <div className="bb-skeleton h-9 w-full" />
          ) : (
            <p className="py-1.5 text-[12px] leading-snug text-text-3">
              {state === "unreachable"
                ? "The audio could not be fetched from this deployment."
                : "No waveform: this browser cannot decode the container. Playback may still work."}
            </p>
          )}
        </div>
        <span className="shrink-0 font-mono text-[11px] text-text-3 tabular">
          {clock(time)} / {duration ? clock(duration) : "–:––"}
        </span>
      </div>
      {meta && meta.length > 0 ? (
        <p className="mt-1.5 flex flex-wrap gap-x-3 pl-12 font-mono text-[11px] text-text-3">
          {meta.map((m) => (
            <span key={m}>{m}</span>
          ))}
        </p>
      ) : null}
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        className="hidden"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setTime(0);
        }}
        onLoadedMetadata={(e) => setDuration(Number.isFinite(e.currentTarget.duration) ? e.currentTarget.duration : 0)}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
      />
    </div>
  );
}

/** A stored turn artefact, labelled with what the bytes say about it. */
export function ArtefactPlayer({ runId, artefact }: { runId: string; artefact: Artefact }) {
  const meta = [
    artefact.variant ?? "stored",
    formatSeconds(artefact.duration_seconds),
    formatHz(artefact.sample_rate_hz),
    artefact.channels ? `${artefact.channels} ch` : null,
    formatBytes(artefact.size_bytes),
    artefact.transformations.length > 0 ? artefact.transformations.join(", ") : null,
  ].filter((m): m is string => Boolean(m));
  return (
    <AudioPlayer
      src={artefactAudioUrl(runId, artefact.turn_index, artefact.variant)}
      label={`turn ${artefact.turn_index} ${artefact.speaker} audio${artefact.variant ? ` (${artefact.variant})` : ""}`}
      meta={meta}
    />
  );
}
