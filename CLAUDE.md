# Nova — CLAUDE.md

## What this project is

Nova is an AI-powered cinematic previsualization tool. A user describes a
scene in plain language; Nova breaks it into a shot list, generates a
controllable storyboard frame per shot (with real cinematographic
parameters — camera, lens, lighting, composition), then compiles locked
shots into short animatic clips with scratch audio and assembles them into
one previs sequence.

Originally built on Bria's FIBO API for a prior hackathon (v1, single-shot
scope). Being rebuilt for the Backblaze Generative AI Media Hackathon
(submission window: June 22 – Aug 3, 2026) as v2: scene-level scope,
model-agnostic, orchestrated through Genblaze, persisted on Backblaze B2.
Full spec lives in `Nova_PRD.md` at repo root — read it before making
architectural changes.

## Technical architecture

### Module layout

```
nova/
  agent/
    scene_breakdown.py      # scene text -> ordered shot list (editable)
    cinematographer.py       # shot description -> Shot Spec (the agent)
    compiler.py               # Shot Spec -> provider-specific prompt/params
                               # (highest-leverage file in the repo — see
                               # "Core concept" above)
  pipeline/
    image_stage.py            # runs Genblaze image pipeline, handles refine loop
    animatic_stage.py         # runs Genblaze video pipeline from locked frame
    audio_stage.py            # runs Genblaze audio pipeline
    assembly.py                # stitches locked animatics + audio into sequence
  storage/
    b2_client.py               # ObjectStorageSink / S3StorageBackend setup
    keys.py                     # canonical B2 key builders (see layout below)
    manifest.py                 # provenance manifest read/write helpers
  webhooks/
    lock_handler.py             # receives B2 Event Notification POST,
                                 # validates signature, calls animatic_stage
  api/
    routes.py                   # HTTP surface for the frontend (scene submit,
                                 # shot refine, lock, sequence fetch)
  models/
    shot_spec.py                # Shot Spec schema + validation
    project.py                  # Project/Scene/Shot state models
```

### Data model and shot states

Each shot moves through a strict state machine. Don't let state leak
implicitly through file existence checks — track it explicitly (DB row or
a `status` field in the project's `scene.json`).

```
DRAFT -> REFINING -> LOCKED -> ANIMATIC_PENDING -> ANIMATIC_READY -> ASSEMBLED
```

- `DRAFT` — Shot Spec created, no frame generated yet
- `REFINING` — one or more frame versions generated (v1, v2, …), user can
  keep refining or lock
- `LOCKED` — user locked a specific version; frame + spec + manifest
  written to B2 under Object Lock; **this write is what fires the B2
  Event Notification**
- `ANIMATIC_PENDING` — webhook received, animatic_stage triggered, waiting
  on Genblaze video pipeline
- `ANIMATIC_READY` — clip + audio persisted to B2
- `ASSEMBLED` — included in the stitched previs sequence

A shot can only be locked from `REFINING` or `DRAFT` (allow locking v1
directly). Refining after lock should create a *new* shot version at
`REFINING`, not mutate the locked one — the locked artifact is immutable
by design (Object Lock enforces this at the storage layer too).

### Shot Spec schema

This is the canonical structure the agent produces and the compiler
consumes. Keep it a single source of truth (`models/shot_spec.py`) — the
compiler, the refine loop, and the manifest all reference it, don't let
copies drift.

```json
{
  "shot_id": "s3",
  "version": 2,
  "intent": "reveal the scale of the drone swarm above the ruined skyline",
  "camera": { "angle": "low", "height_m": 1.2, "movement": "slow push-in" },
  "lens": { "focal_length_mm": 18, "aperture_f": 2.8 },
  "framing": { "shot_size": "extreme wide", "composition": "rule-of-thirds, subject lower-left" },
  "lighting": { "key": "low-key", "mood": "dramatic shadows", "practicals": ["drone lights"] },
  "grade": { "look": "desaturated teal", "contrast": "high" },
  "subject": { "primary": "woman in tattered coat", "blocking": "walking left-to-right, foreground" },
  "world": ["destroyed buildings", "dumped cars", "airborne drones", "dense fog"],
  "continuity_refs": ["s1_frame", "s2_frame"]
}
```

`continuity_refs` point at *locked* frame B2 keys from earlier shots in
the same scene — pass these as reference images to the image stage
(nano-banana supports this) to hold character/world consistency across
shots. This is the main compensating mechanism for not having FIBO's
native determinism anymore; don't drop it during refactors.

### Pipeline stage interface

Keep every stage the same shape so orchestration code doesn't special-case
per stage:

```python
class PipelineStage(Protocol):
    def run(self, shot_spec: ShotSpec, sink: ObjectStorageSink) -> StageResult: ...

class StageResult:
    status: Literal["succeeded", "failed"]
    assets: list[Asset]       # empty if failed
    manifest_key: str          # B2 key of the provenance manifest
    error: str | None
```

Image stage additionally exposes `refine(shot_spec, prior_version) ->
StageResult` for the iterative loop — don't reuse `run()` for refinement,
the prompt construction differs (edit-in-place vs generate-from-scratch).

Always check `StageResult.status` before touching `.assets` — this
matters especially in fan-out (multi-take) calls where some parallel
branches can fail while others succeed.

### B2 key structure

```
nova-previs/
  projects/{project_id}/
    scene.json
    shots/{shot_id}/
      spec/v{n}.json
      frames/v{n}.png
      locked/
        frame.png            <- Object Lock; write here fires the webhook
        manifest.json         <- Object Lock
      animatic/
        clip.mp4
        audio.mp3
    previs/
      sequence.mp4
      manifest.json
```

Build these keys through `storage/keys.py`, never string-format them
inline elsewhere — the webhook handler matches on the `locked/frame.png`
suffix, so any code that writes a locked frame to a different path
silently breaks the trigger.

### Webhook handler (the Nova-built glue, not a Genblaze feature)

1. Configure a B2 Event Notification rule: `b2:ObjectCreated:*` scoped to
   path prefix `projects/*/shots/*/locked/frame.png`, webhook URL pointing
   at `webhooks/lock_handler.py`.
2. Handler validates the `x-bz-event-notification-signature` header
   against the configured signing secret before doing anything else.
3. Respond `200` within B2's 3-second timeout window immediately; do the
   actual animatic-stage call asynchronously (queue/background task), not
   inline in the request handler — B2 will treat a slow response as a
   delivery failure and retry (at-least-once delivery, so the handler
   must also be idempotent: check current shot status before
   re-triggering).
4. On success, update shot status to `ANIMATIC_PENDING` then
   `ANIMATIC_READY` once Genblaze's animatic_stage completes.

Reminder: this webhook path is B2's native Event Notifications feature.
Genblaze itself does not know about or participate in this trigger — it
only runs the pipeline stage once called.

## Tech stack

- Python, `genblaze-core` for pipeline orchestration
- Provider adapters: `genblaze-openai`, `genblaze-google` (Gemini 2.5
  Flash Image / nano-banana, primary image model), `genblaze-runway`,
  `genblaze-luma`, `genblaze-gmicloud` (Flux draft tier, Decart draft
  video)
- `genblaze-s3` with `S3StorageBackend.for_backblaze("bucket-name")` for
  B2 persistence
- Audio: Stability Audio (ambient/score), ElevenLabs (scratch VO)

## Working style (apply throughout)

- Explain reasoning and tradeoffs, not just the answer. If there are two
  reasonable ways to build something, say so and why one was chosen.
- Flag hacks and shortcuts distinctly and explicitly — don't let a
  workaround blend in as if it were the intended design.
- Minimize clarifying questions. Pick the most reasonable interpretation,
  state the assumption inline, and proceed.

## Critical rule: verify SDK claims before asserting them

This project's PRD already had one real overclaim caught and corrected:
it originally stated Genblaze consumes/fires B2 Event Notifications
natively. It doesn't — B2 Event Notifications is a native B2 platform
feature (webhook-based), and the trigger-the-next-stage logic is
hand-built glue code in Nova, not a Genblaze feature.

**Because judges/reviewers for this hackathon are Backblaze engineers,
overclaiming what `genblaze-core`/`genblaze-s3` do natively is a fast way
to lose credibility on exactly the criteria being optimized for.**

Rule going forward: before writing docs, PRD language, or code comments
that assert "Genblaze does X natively" or "B2 does Y automatically,"
check the actual behavior — read `github.com/backblaze-labs/genblaze`
source/docs or the relevant PyPI package description directly. Do not
infer plausible-sounding SDK behavior from general knowledge of what a
"media orchestration SDK" should do. If a capability can't be confirmed,
either mark it explicitly as "to be hand-built" or don't claim it.

Confirmed-native as of last check (re-verify if package versions bump):
Object Lock retention on manifests, SHA-256 provenance embedded in
output files, `fallback_models=[...]` retry chains, fan-out execution
with per-step status, `ObjectStorageSink` / `S3StorageBackend.for_backblaze()`.

Confirmed NOT native: Genblaze does not consume or emit B2 Event
Notifications. That wiring is Nova's own webhook handler.

## Submission constraints (Backblaze hackathon official rules)

- Project pre-dates this hackathon (built for FIBO hackathon) — this is
  allowed under the "New & Existing" rule, but B2 + Genblaze integration
  must happen after the Submission Period start (June 22, 2026, 10am ET),
  and the submission text must explicitly explain what was significantly
  updated during the period.
- Submission needs: working app URL, public/private GitHub repo (grant
  judge access if private), text description covering B2 + Genblaze usage
  and provider/model list, ≤3-min demo video (YouTube/Vimeo/Youku).
- Do not use FIBO/Bria as the image generation provider in this version —
  it's being removed and replaced per the PRD.

## Vocabulary

- **Shot Spec** — the cinematographic IR per shot (see above)
- **Lock** — user finalizes a shot's frame; triggers persistence +
  downstream animatic generation
- **Previs sequence** — the final assembled output (stitched animatics)
- **FIBO** — Bria's prior image API Nova v1 was built on; being removed
- **Genblaze** — Backblaze's orchestration SDK; see verification rule
  above before asserting anything about its behavior