# Nova — File Structure

**Status:** Draft
**Companion to:** `Nova_PRD.md` (product spec), `CLAUDE.md` (backend
conventions), `schema/shot_spec.schema.json` (Shot Spec contract)

## Purpose

This document is meant to travel with the design doc, page list, and user
flow when frontend/UI work gets handed to another tool. It defines where
things live and the seams between what already exists (backend, schema)
and what's being built (frontend). Treat the "Rules for whoever builds
the frontend" section as directive, not suggestion — it exists so a tool
that has never seen this repo can generate code that actually integrates
instead of needing to be re-plumbed afterward.

**Two things this document is *not*:** it doesn't define the API contract
(that's backlog 1.4, still open — see "Open dependency" below) and it
doesn't cover pages/user flow/visual design (that's the design doc this
travels alongside, which you're authoring separately).

## Architecture recap (why the structure looks like this)

One deployable, not two. `nova/api/app.py` (FastAPI) serves both the
JSON API and the built frontend as static files from the same process —
decided in backlog 0.4 specifically to avoid CORS and to keep a single
uptime surface for judging. This means the frontend is a plain SPA build
(Vite output, no Node server at runtime), not a Next.js app with its own
server. See `README.md` "Tech stack" for the full rationale.

## Full tree

```
nova-previs/
├── CLAUDE.md                        backend conventions, architecture rules
├── Nova_PRD.md                      product spec — source of truth for behavior
├── Nova_Backlog.csv                 task tracker
├── Nova_File_Structure.md           this document
├── README.md                        setup, tech stack decision, CI
├── LICENSE
├── .env.example                     copy to .env; keyID / applicationKey
├── .gitignore
├── pyproject.toml                   nova/ package config, ruff, pytest
├── requirements.txt                 Python deps
├── .github/workflows/ci.yml         ruff + pytest on push/PR
│
├── schema/
│   └── shot_spec.schema.json        generated from nova/models/shot_spec.py —
│                                     do not hand-edit, regenerate via the script below
│
├── scripts/
│   ├── setup_b2_bucket.py           provisions the nova-previs B2 bucket
│   └── export_shot_spec_schema.py   regenerates schema/shot_spec.schema.json
│
├── nova/                            backend Python package (installed editable: pip install -e .)
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── shot_spec.py             LOCKED (backlog 1.1) — the Shot Spec IR. Do not modify
│   │   │                            without updating schema/shot_spec.schema.json to match.
│   │   └── project.py               NOT YET BUILT — Project/Scene/Shot state models,
│   │                                the DRAFT→...→ASSEMBLED state machine (see CLAUDE.md)
│   ├── agent/                       NOT YET BUILT
│   │   ├── scene_breakdown.py       scene text -> ordered shot list
│   │   ├── cinematographer.py       shot description -> Shot Spec
│   │   └── compiler.py              Shot Spec -> provider-specific prompt/params
│   ├── pipeline/                    NOT YET BUILT
│   │   ├── image_stage.py
│   │   ├── animatic_stage.py
│   │   ├── audio_stage.py
│   │   └── assembly.py
│   ├── storage/                     NOT YET BUILT
│   │   ├── b2_client.py             ObjectStorageSink / S3StorageBackend setup
│   │   ├── keys.py                  canonical B2 key builders — ALL B2 paths go through
│   │   │                            this module, never string-formatted inline (see CLAUDE.md)
│   │   └── manifest.py
│   ├── webhooks/                    NOT YET BUILT
│   │   └── lock_handler.py          receives B2 Event Notification POST
│   └── api/                         NOT YET BUILT
│       ├── __init__.py
│       ├── app.py                   FastAPI app entrypoint; mounts frontend/dist/ as
│       │                            static files at "/"; all API routes under "/api"
│       └── routes.py                scene submit, shot refine, lock, sequence fetch —
│                                     contract not finalized yet, see "Open dependency" below
│
├── tests/                           pytest, mirrors nova/ by concern (not 1:1 by file)
│   ├── test_b2_connection.py
│   ├── test_b2_bucket_setup.py
│   └── test_shot_spec.py
│
└── frontend/                        NOT YET BUILT — this is what gets offloaded
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── index.html
    ├── public/
    ├── dist/                        build output — gitignored, mounted by nova/api/app.py
    └── src/
        ├── main.tsx
        ├── App.tsx                  router root — see "Pages" below for the 6 screens
        ├── api/
        │   └── client.ts            typed fetch wrapper for /api/* — one file, not scattered fetches
        ├── types/
        │   └── shotSpec.ts          hand-mirror (or codegen from) schema/shot_spec.schema.json —
        │                            keep in lockstep with the Python model, it's the same contract
        ├── pages/                   one file per PRD §5 core-experience screen (backlog 1.2/8.x)
        │   ├── SceneInput.tsx               step 1: scene description entry
        │   ├── ShotListEditor.tsx           step 2: agent-proposed, user-editable shot list
        │   ├── StoryboardGrid.tsx           step 3: per-shot stills + refine panel
        │   ├── PrevisViewer.tsx             step 6: assembled sequence + share link
        │   └── (lock action + status indicators are UI state within StoryboardGrid,
        │        not a separate page — see backlog 8.4)
        ├── components/
        │   ├── ui/                  shadcn/ui primitives (generated, not hand-written)
        │   ├── ShotCard.tsx
        │   ├── RefinePanel.tsx
        │   ├── VersionScrubber.tsx  backlog 3.7 — scrub v1..vN
        │   ├── StatusBadge.tsx      DRAFT/REFINING/LOCKED/.../ASSEMBLED
        │   └── TakePicker.tsx       backlog 8.6 — multi-take fan-out selection
        ├── hooks/
        │   └── useShotStatus.ts     TanStack Query, 2–3s poll — see README "Tech stack"
        └── lib/
            └── utils.ts
```

## Rules for whoever builds the frontend

1. **`frontend/` is the entire footprint.** Nothing outside it. Don't touch `nova/`, `schema/`, `scripts/`, or root config files — those are backend-owned.
2. **Read `schema/shot_spec.schema.json` before designing any shot-editing UI.** It's the exact field list, types, and enums the backend will accept — e.g. `camera.angle` is a closed 7-value enum, not free text; building a free-text input for it will just fail validation later. Mirror it into `frontend/src/types/shotSpec.ts`.
3. **All API calls go through `frontend/src/api/client.ts`, prefixed `/api/`.** No direct `fetch()` calls scattered across components — this is what keeps the eventual real backend wiring (once 1.4 lands) a one-file change.
4. **No routing collision with the API.** `nova/api/app.py` reserves `/api/*` for JSON endpoints; everything else falls through to the SPA. Don't name a frontend route `/api/anything`.
5. **Status polling, not WebSockets, for MVP.** Matches the backend's `BackgroundTasks` model (no persistent connection to manage) — see README "Tech stack" for why.
6. **Build output is `frontend/dist/`.** That's the literal path `nova/api/app.py` mounts. Changing it requires a corresponding backend change — flag it, don't just rename.
7. **Don't invent new Shot Spec fields in the UI.** The schema is locked (backlog 1.1) on purpose — the compiler's provider-mapping logic depends on the enum being closed. If a screen needs a field that doesn't exist, that's a schema change to raise, not a UI-only workaround.

## Housekeeping (existing repo debt, not new work)

- `main.py` at the repo root is unmodified PyCharm boilerplate from before this project's scaffolding — it should be deleted once `nova/api/app.py` becomes the real entrypoint, so there's only one obvious place to run the app from.

## Open dependency: this doc assumes an API contract that doesn't exist yet

Backlog 1.4 ("Define frontend/backend API contract") hasn't been done.
`nova/api/routes.py` above is a reserved location, not a working contract.
Handing the frontend off before 1.4 lands means it'll build against
assumed request/response shapes that may not match what `nova/api/routes.py`
ends up returning — recommend doing 1.4 first, or in parallel with very
explicit mocked responses the frontend tool treats as provisional. Either
way, don't let the frontend tool silently invent the contract; that's the
fastest way to end up rebuilding it.
