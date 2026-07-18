# Devpost submission text — DRAFT (backlog 11.1)

Status: draft. Placeholders in `[brackets]` must be filled before submitting
(live app URL, repo visibility, video link). Every SDK claim below follows
CLAUDE.md's verify-before-asserting rule — nothing here says "Genblaze does
X natively" unless it was confirmed against the installed SDK source.

---

## Nova — cinematic previsualization from a sentence

**Live app:** `[URL — task 11.4]` · **Repo:** `[github.com/godfatherc08/…]`
· **Demo video:** `[YouTube link — task 12.6]`

### What it does

Describe a scene in plain language. Nova's cinematographer agent breaks it
into an ordered, fully editable shot list, then authors a **Shot Spec** per
shot — a structured cinematographic IR (camera angle/height/movement, lens
focal length and aperture, framing, lighting key and mood, grade, subject
blocking, world elements) instead of a prompt blob. A compiler turns each
Shot Spec into provider-specific calls, so every creative parameter stays
inspectable and editable. You refine frames with natural-language notes
(each refinement is a new immutable version), lock the take you want, and
Nova automatically carries the locked frame through animatic video and
scratch audio into one assembled, shareable previs sequence with a
verifiable provenance chain.

### How we use Backblaze B2

- **Single source of truth for every artifact.** Scene JSON, versioned Shot
  Specs, every frame version, locked frames, provenance manifests, animatic
  clips, audio tracks, and the final sequence all live in one `nova-previs`
  bucket under a canonical key layout (`projects/{id}/shots/{id}/…`).
- **Object Lock as a product feature, not a checkbox.** "Locking" a shot is
  literally a B2 Object Lock write: the chosen frame + its sealed manifest
  become immutable at the storage layer. Refining after lock creates a new
  version; the locked take can never be silently altered — that's the
  chain-of-custody story for downstream production.
- **B2 Event Notifications drive the pipeline.** The Object-Locked
  `locked/frame.png` write fires a B2 Event Notification to Nova's webhook
  (signature-validated, ACKed inside B2's 3-second window, idempotent
  against at-least-once redelivery), which triggers animatic + audio
  generation with no manual step. A polling fallback sweeps missed events.
  This event wiring is Nova's own glue code on top of B2's native feature.
- **Lifecycle rules** auto-expire rejected takes and scratch artifacts;
  **durable URLs** back the share pages, so a previs link keeps working
  from a fresh browser with no auth.

### How we use Genblaze

Every generation call in Nova runs through a real `genblaze-core`
`Pipeline`. Confirmed-native features we lean on: `fallback_models` retry
chains, fan-out execution with per-step status (multi-take generation),
SHA-256 provenance embedded in outputs, Object Lock retention support, and
`ObjectStorageSink` / `S3StorageBackend.for_backblaze()` for B2
write-through.

We also **extended** Genblaze through its public `SyncProvider` extension
point: `genblaze-google`'s `ImagenProvider` serves the Imagen API and
accepts no image inputs, so it can't run Gemini 2.5 Flash Image
("nano-banana") or carry reference frames. Nova ships its own first-class
Gemini provider adapter that does both — reference-image continuity across
shots is the core consistency mechanism. We're filing the gaps we found
(including a Windows `file://` parsing bug in `genblaze-core`'s storage
transfer) as upstream issues — see `docs/genblaze_feedback.md`.

### Providers and models

| Stage | Primary | Fallbacks |
|---|---|---|
| Agent LLM (breakdown, Shot Specs, refine) | OpenAI via `genblaze-openai` | schema-validated retry loop |
| Storyboard frames | Gemini 2.5 Flash Image ("nano-banana", Nova adapter) | gpt-image-1 (`genblaze-openai`) → Flux draft (`genblaze-gmicloud`) |
| Animatic video | Runway `gen4_turbo` (`genblaze-runway`) | Luma `ray-2` (`genblaze-luma`) → GMI draft video |
| Scratch audio | Stability Audio (Nova adapter) | ElevenLabs SFX `eleven_text_to_sound_v2` (`genblaze-elevenlabs`) |
| Assembly | ffmpeg concat + per-shot audio mux | — |

### New vs. existing work (required disclosure)

Nova v1 was built for Bria's FIBO hackathon: single-shot scope, FIBO as the
only image model, no persistence layer. Everything that makes this
submission was built during the Submission Period (after June 22, 2026):

- FIBO removed entirely; rebuilt model-agnostic on Genblaze pipelines with
  cross-provider fallback chains at every stage.
- Scene-level scope: shot-list agent, Shot Spec IR + compiler, refine loop
  with versioning, multi-take fan-out.
- The whole B2 layer: bucket layout, Object Lock locking, provenance
  manifests + verification utility, Event Notification webhook + polling
  fallback, lifecycle rules, durable share links.
- Animatic, audio, and assembly stages; the full React frontend.

### Judge access

`[If repo is private: judge GitHub usernames granted read access — task
11.3. Test credentials if auth is added: …]`
