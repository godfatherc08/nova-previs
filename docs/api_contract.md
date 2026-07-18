# Nova API Contract (backlog 1.4)

The implementation is `nova/api/routes.py`; the TypeScript mirror the
frontend consumes is `frontend/src/lib/api.ts`. This document is the
human-readable index — if it ever disagrees with those two, they win.

All JSON endpoints are under `/api`. The webhook surface
(`/webhooks/b2/lock`) is documented separately in `docs/error_ux.md` and
`CLAUDE.md`; it is machine-to-machine, not part of this contract.

## Conventions

- Request/response bodies are JSON. Errors use FastAPI's `{"detail": "..."}`
  shape; the frontend surfaces `detail` verbatim.
- A **failed provider** is *not* an HTTP error. Generation endpoints return
  `200` with the shot's `error` field populated and `status` unchanged —
  the UI renders a retryable error card. HTTP `5xx` is reserved for genuine
  infrastructure failure (B2 unreachable, agent LLM down).
- Media is served through `GET /api/media/{key}` (the bucket is private).
  All `*_url` fields in responses are these proxy paths, never raw B2 URLs.

## State machine

`DRAFT → REFINING → LOCKED → ANIMATIC_PENDING → ANIMATIC_READY → ASSEMBLED`

A shot locks only from `DRAFT`/`REFINING`. Refining a locked shot creates a
new `REFINING` version; the locked artifact stays immutable (Object Lock
enforces this in B2 too).

## Endpoints

| Method | Path | Purpose | Backlog |
|--------|------|---------|---------|
| POST | `/projects` | Create project; agent proposes a shot list | 2.1 |
| GET | `/projects` | List project summaries | 2.1 |
| GET | `/projects/{id}` | Fetch project + shots (poll target) | 2.1 |
| PUT | `/projects/{id}/shot-list` | Replace shot list (add/remove/reorder/edit) | 2.2 |
| POST | `/projects/{id}/generate-storyboard` | Author a v1 Shot Spec per shot (DRAFT) | 2.4 |
| POST | `/projects/{id}/shots/{sid}/generate` | Run image stage → frame for current version | 3.1/3.5 |
| POST | `/projects/{id}/shots/{sid}/refine` | Instruction → new spec version → regenerated frame | 3.6 |
| PUT | `/projects/{id}/shots/{sid}/spec` | Manual spec edit → new version | 3.7 |
| POST | `/projects/{id}/shots/{sid}/lock` | Write Object-Locked frame + sealed manifest | 4.1 |
| GET | `/projects/{id}/shots/{sid}/manifest` | Fetch the locked shot manifest | 4.2 |
| POST | `/projects/{id}/shots/{sid}/takes` | Fan out N parallel candidate takes | 8.6 |
| POST | `/projects/{id}/shots/{sid}/takes/promote` | Promote a take to a numbered version | 8.6 |
| POST | `/projects/{id}/assemble` | Stitch ANIMATIC_READY shots into the previs | 7.1 |
| GET | `/projects/{id}/manifest` | Fetch the full-chain sequence manifest | 7.3 |
| GET | `/media/{key}` | Stream a private-bucket object (durable link) | 4.3/7.4 |

## Core response shapes

`Project`:

```json
{
  "project_id": "…", "scene_text": "…",
  "shot_list": [ { "shot_id": "s1", "order": 0, "description": "…",
                   "intent": "…", "shot_size": "wide" } ],
  "shots": [ Shot ],
  "sequence_url": "/api/media/projects/…/previs/sequence.mp4" | null,
  "sequence_manifest_url": "…" | null,
  "created_at": "…", "updated_at": "…"
}
```

`Shot`:

```json
{
  "shot_id": "s1", "order": 0, "status": "REFINING",
  "description": "…", "current_version": 2,
  "versions": [ { "version": 1, "frame_url": "/api/media/…" | null,
                  "spec": ShotSpec, "created_at": "…" } ],
  "locked_frame_url": "…" | null,
  "animatic_clip_url": "…" | null,
  "animatic_audio_url": "…" | null,
  "manifest_url": "…" | null,
  "error": "…" | null
}
```

`ShotSpec` is the schema in `schema/shot_spec.schema.json` (generated from
`nova/models/shot_spec.py`). `takes` returns
`{ "takes": [ { "take_id": "v2-t1", "frame_url": "…" } ], "errors": [] }`.

## Polling

The frontend polls `GET /projects/{id}` every ~2.5s while any shot is in a
transient state (`DRAFT`, `REFINING`, `ANIMATIC_PENDING`) and stops when all
shots settle. Matches the backend's `BackgroundTasks` model — no
SSE/WebSocket to manage for MVP.
