# Fallback & Error UX States (backlog 1.6 / 9.3)

How Nova presents provider stalls, generation failures, and retries. The
guiding principle: a failed provider is a *normal* state in a
multi-provider pipeline, not a crash — so the UI treats it as a recoverable
card, and the pipeline keeps its own state honest.

## Layered handling

| Layer | Mechanism |
|-------|-----------|
| Provider call | Each adapter maps errors into Genblaze's `ProviderErrorCode` taxonomy so the retry layer treats transient vs. permanent correctly. |
| Stage | Cross-provider fallback chain (nano-banana→gpt-image-1→Flux; Runway→Luma→GMI; Stability→ElevenLabs). Returns a `StageResult(status="failed", error=…)`, never raises. |
| API | Generation endpoints return `200` with `shot.error` set — not a `5xx`. Only infra failure (B2 down, agent LLM down) is a `5xx`. |
| Frontend | Per-request error card + retry; a top-level `ErrorBoundary` for unexpected render crashes. |

## The three UI states (mockups)

### 1. Retry-in-progress (fallback firing)
The primary provider failed and a fallback is being tried. The user sees the
same "Generating frame" leader countdown — the fallback is invisible unless
the whole chain fails. (The model that actually served is recorded in the
manifest, so provenance stays truthful.)

```
┌ Camera report — s2 · v2 · REFINING ─┐
│      ◔  3 · 2 · 1  Generating frame │
└──────────────────────────────────────┘
```

### 2. Generation failed (whole chain exhausted)
Every provider in the chain failed. The frame area shows the error and a
retry button; the shot stays at its prior status (not advanced).

```
┌ Camera report — s2 · v2 · DRAFT ────┐
│  ⚠ Generation failed: all providers │
│    in the fallback chain failed …   │
│         [ Retry generation ]        │
└──────────────────────────────────────┘
```

### 3. Degraded success (audio dropped)
The animatic clip generated but the audio stage failed for that shot. This
is graceful degradation, not failure: the shot reaches `ANIMATIC_READY`, the
sequence assembles with a **silent track** for that shot, and the shot's
`error` carries an `audio degraded: …` note the UI can surface as a subtle
badge rather than a blocking card.

```
┌ s3  ANIMATIC_READY  ⚑ audio degraded ┐
└───────────────────────────────────────┘
```

### 4. Project/API unavailable
A failed project fetch (bad id, API down) shows a centered recovery state
with a route back to `/new`. The top-level `ErrorBoundary` catches anything
that slips past per-request handling and offers "Back to start", reassuring
the user that locked artifacts are persisted in B2.

## Reliability backstops (not user-visible, but why the UX can stay calm)

- **At-least-once webhook delivery** + idempotent advance: a duplicate lock
  event is a no-op.
- **Polling fallback** (`scripts/run_poller.py`): shots stuck in `LOCKED`
  (missed event, or a failed prior animatic attempt) get retried
  automatically, so a transient stall self-heals without user action.
- **Object Lock**: a locked frame/manifest cannot be corrupted mid-pipeline,
  so "your work is saved" in the error copy is literally true.
