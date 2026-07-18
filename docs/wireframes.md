# Wireframes / Screen Flow (backlog 1.2)

Documents the six core-experience screens (PRD §5) as built in `frontend/`.
The frontend is implemented, so these are as-built reference wireframes, not
speculative sketches. Routes are in `frontend/src/App.tsx`.

## Flow

```
Landing (/)  ──"Start a scene"──▶  New Scene (/new)
                                        │ submit scene text
                                        ▼
                              Storyboard (/p/:id)  ── shot-list phase
                                        │ generate storyboard
                                        ▼
                              Storyboard (/p/:id)  ── storyboard phase
                                        │ all shots ANIMATIC_READY → assemble
                                        ▼
                              Sequence (/p/:id/sequence)

Projects (/projects) lists prior projects → deep-links into Storyboard.
```

## 1. Landing (`routes/Landing.tsx`)
Muybridge-inspired hero (the galloping-horse motion study — the origin of
previs). Single CTA into the scene input. Cinematic shell: film grain,
letterbox bars, key-light cursor.

```
┌────────────────────────────────────────────┐
│ ░░ letterbox ░░                             │
│                                             │
│        N O V A                              │
│        cinematic previsualization           │
│        [ Start a scene ]   [ Projects ]     │
│                                             │
│ ░░ letterbox ░░                             │
└────────────────────────────────────────────┘
```

## 2. New Scene (`routes/NewScene.tsx`) — PRD step 1
Large free-text scene description entry. Submit → `POST /projects` → routes
to Storyboard.

## 3. Storyboard, shot-list phase (`routes/Storyboard.tsx`) — PRD step 2
Agent-proposed shot list. Each row: drag handle (reorder), description +
intent, shot_size tag, remove. Add shot / Save / **Generate storyboard**.

```
┌ Shot list ─────────────────────────────────┐
│ ⠿ 01  [ description textarea ]  [size] [x]  │
│ ⠿ 02  [ description textarea ]  [size] [x]  │
│ [ Add shot ] [ Save ] [ Generate storyboard]│
└─────────────────────────────────────────────┘
```

## 4. Storyboard, storyboard phase — PRD steps 3–5
Left: a horizontal **ShotStrip** (film-strip of frames, rack-focus on
hover, status badge per shot). Right: **ShotDetailPanel** — the "camera
report": frame preview, version scrubber (v1..vN, backlog 3.7), tabbed Shot
Spec editor (closed-enum selects + free-text), refine input, lock button.
Below: **TakePicker** (multi-take fan-out, backlog 8.6) and a provenance
drawer.

```
┌ Storyboard ────────────────────────────────────────────┐
│ [f1][f2][f3][f4]  ← ShotStrip (status badges)           │
│ ┌ Camera report — s2 · v2 · REFINING ─────────────────┐ │
│ │  [ frame preview / Generating… / error+Retry ]      │ │
│ │  v1  v2                        ← version scrubber    │ │
│ │  (Camera|Lens|Framing|Lighting|Grade|Subject|World|  │ │
│ │   continuity_refs)  ← tabbed spec editor             │ │
│ │  [ refine instruction …………… ]   [ Lock shot ]        │ │
│ └──────────────────────────────────────────────────────┘│
│ [ Multi-take: 2 / 3 takes → promote ]                    │
└──────────────────────────────────────────────────────────┘
```

Lock/status indicators (backlog 8.4) are inline state, not a separate
screen: the status badge + `LeaderCountdown` spinners + the MatchCut
animation when a still becomes an animatic.

## 5. Lock action — PRD step 4
`LockConfirm` dialog on the detail panel. Disabled until a frame exists.
After lock the shot advances DRAFT/REFINING → LOCKED → ANIMATIC_PENDING →
ANIMATIC_READY, reflected live by polling.

## 6. Sequence viewer (`routes/Sequence.tsx`) — PRD step 6
Playback of the assembled previs, the durable share link (`ShareLink`), and
a `ProvenancePanel` exposing the chain-of-custody manifest.

```
┌ Previs ────────────────────────────────────┐
│  ▶ [ assembled sequence.mp4 ]               │
│  Share: https://…/api/media/…/sequence.mp4  │
│  [ Provenance ▾ ]  chain of N locked shots  │
└─────────────────────────────────────────────┘
```
