# Visual Design System (backlog 1.3)

As-built design language of the Nova frontend. Tokens live in
`frontend/src/styles/tokens.css`; primitives are shadcn/ui + Tailwind in
`frontend/src/components/ui/`.

## Concept

Nova is a *filmmaking* tool, so the UI reads like a camera department, not a
SaaS dashboard: near-black stage, letterbox framing, film grain, a key-light
that tracks the cursor, and "leader countdown" spinners. The interface
recedes so the frames are the subject.

## Color tokens

| Token | Value | Use |
|-------|-------|-----|
| `--black` | `#0a0a0a` | stage background |
| `--film-base` | `#161616` | panels, cards |
| `--graphite` | `#4a4a4a` | borders, dividers |
| `--silver` | `#8c8c8c` | secondary text, labels |
| `--light` | `#f5f5f3` | primary text |
| `--key` | `#ffffff` | key-light highlight |
| `--leader-amber` | `#e0a45c` | countdown/leader accent; also the warning tone |

Deliberately near-monochrome. The only chroma is the amber "leader" accent
(the countdown numbers on film leader) — used for in-progress and warning
states so attention lands exactly where generation is happening.

## Type

- **Display**: Anton / Archivo Black — condensed uppercase, for headings
  ("CAMERA REPORT", "STORYBOARD"). Evokes slate/title-card lettering.
- **Body**: Inter.
- **Mono**: JetBrains Mono — for IDs, versions, statuses, technical fields
  (focal length, f-stop) — the "camera report" register.

## Letterbox / aspect stages

The shell reframes per route via `data-stage` (`App.tsx`):

- `academy` (1.375) — landing/scene input, tall bars.
- `widescreen` (1.85) — storyboard/project work.
- `scope` (2.39) — sequence playback, bars gone.

The aspect ratio itself is a wayfinding cue: you *feel* the move from
authoring to viewing.

## Motion

`lib/motion.ts` centralizes easing/durations. Signature moments: a subtle
dolly (scale) on entering the storyboard, a rack-focus on the shot strip,
and a **MatchCut** when a still becomes an animatic (still → motion, the
core product moment). All motion respects `prefers-reduced-motion`
(`useReducedMotion`) — reduced users get the state change without the
animation.

## Components

shadcn/ui primitives (button, input, select, tabs, sheet, alert-dialog,
etc.) restyled to the tokens above. Composite components: `ShotStrip`,
`ShotCard`, `ShotDetailPanel`, `RefineInput`, `LockConfirm`, `TakePicker`,
`VersionScrubber` (inline in the panel), `SequencePlayer`, `ShareLink`,
`ProvenancePanel`, plus the shell (`FilmGrain`, `KeyLightCursor`,
`Letterbox`, `ErrorBoundary`).

## Accessibility

- Reduced-motion honored throughout.
- Closed-enum spec fields use real `<Select>`s (keyboard + screen-reader
  navigable), not free text — which also keeps them schema-valid.
- Drag-to-reorder has a keyboard sensor (`@dnd-kit`
  `sortableKeyboardCoordinates`).
- Status is conveyed by text badge + label, not color alone.
