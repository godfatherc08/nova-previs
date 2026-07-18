# Demo video script (backlog 12.1) + demo scene choice (12.2)

Hard limit 3:00. This script times to ~2:40 read aloud at a normal clip,
leaving cut room. Narration must explicitly name B2 and Genblaze usage
(judging criteria — task 12.4), and per CLAUDE.md nothing in the VO claims
SDK behavior that isn't real.

## Demo scene (12.2 decision)

**"A lone courier sprints across a rain-slick rooftop at night while a
drone swarm rises out of the fog behind the skyline; she leaps the gap
between buildings as searchlights sweep up."**

Why this one: 5–6 natural shots (establishing wide → tracking medium →
low-angle drone reveal → close-up → jump wide → aftermath); fog + drones +
searchlights exercise lighting/practicals fields of the Shot Spec; the
recurring courier across shots shows continuity_refs doing real work; and
motion (sprint, leap, rising swarm) makes the animatic stage visibly earn
its keep. Pre-run it end-to-end before recording (acceptance criterion) —
record against a project that has already generated once so provider
latency doesn't eat the runtime; regenerate one shot live instead.

## Shot-by-shot script

| # | Time | Screen | Voiceover |
|---|---|---|---|
| 1 | 0:00–0:15 | Landing page → type the scene description | "This is Nova. You describe a scene once — and get a filmable previs. Watch the whole pipeline: storyboard, animatics, audio, final sequence." |
| 2 | 0:15–0:35 | Shot list appears; delete one shot, drag-reorder, reword one | "Nova's cinematographer agent breaks the scene into shots. It's a proposal, not a verdict — cut, reorder, reword. Every shot then gets a Shot Spec: real cinematographic parameters — lens, camera height, lighting key — not a prompt blob." |
| 3 | 0:35–1:00 | Storyboard grid fills; open one Shot Spec panel | "Frames generate through Genblaze pipelines — Gemini's nano-banana first, with automatic fallback to gpt-image-1 and Flux if a provider fails. We extended Genblaze with our own provider adapter to get reference-image continuity across shots." |
| 4 | 1:00–1:20 | Type a refine note ("lower angle, more fog"); new version appears; scrub v1↔v2 | "Refine in plain language. Every take is a new version — nothing is overwritten, and you can walk the history." |
| 5 | 1:20–1:50 | Hit Lock; show status walking LOCKED → animatic-pending → animatic-ready | "Locking is the interesting part. The frame and its provenance manifest are written to Backblaze B2 under Object Lock — immutable at the storage layer. That write fires a B2 Event Notification to our webhook, which kicks off animatic and audio generation automatically. No button. The storage event *is* the pipeline trigger." |
| 6 | 1:50–2:10 | (Pre-staged) forced primary failure: show a shot that completed via fallback badge/log | "Reliability is designed in: kill the primary video provider and Genblaze's fallback chain finishes the clip on Luma. Every stage degrades gracefully." |
| 7 | 2:10–2:35 | Sequence page: play the assembled previs with audio; copy share link, open in incognito | "Locked shots assemble into one sequence with scratch audio — stored on B2 with a durable link that just works, plus a manifest chain you can independently verify, hash by hash." |
| 8 | 2:35–2:50 | Provenance panel / verify utility output; end card with URL + repo | "Scene to shareable, verifiable previs in one sitting. Nova — built on Backblaze B2 and Genblaze." |

## Production notes (feeds 12.3–12.6)

- Record at 1920×1080, hide bookmarks bar, 125% zoom for legibility.
- Capture raw footage of the *live deployed URL*, not localhost (judges
  see the same surface they'll test — task 11.6).
- Fallback beat (#6): stage it by unsetting the Runway key in the deployed
  env for that one shot, or pre-record it — do not improvise it live.
- No copyrighted music (official rules); Nova's own generated scratch
  audio is the soundtrack — which is itself a flex.
- Upload public on YouTube (12.6), then attach to Devpost (12.7).
