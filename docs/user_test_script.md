# Moderated user-test script (backlog 10.2)

Covers all 6 core experience steps (PRD §5): describe → edit shot list →
storyboard → refine → lock → view/share previs. Target session length:
25–30 min. Run against the deployed URL (not localhost) once 9.4 passes.

## Setup (before participant joins)

- Fresh browser profile, screen + audio recording on, timer ready.
- Providers healthy: run one throwaway generation end-to-end first.
- Note participant persona: filmmaker / ad creator / film student.

## Intro (2 min, read aloud)

"Nova turns a scene description into a filmable previs. I'll give you
goals, not instructions — narrate your thinking as you go. Nothing you do
can break it, and we're testing the tool, not you."

## Tasks

Record for each: completion (unaided / aided / failed), time, quotes,
friction points.

1. **Describe a scene** — "Bring a scene from a project you know into
   Nova — or use: *a courier races through a flooded night market as
   drones close in*." ✓ Scene submitted, shot list appears.
   *Metric: time from landing to shot list.*
2. **Shape the shot list** — "Make this list yours: remove one shot you
   don't need, reorder two, reword one." ✓ All three edits persist.
3. **Generate the storyboard** — "Get frames for your shots." ✓ Grid
   populates; participant can explain what a Shot Spec field means.
   *Metric: do they open/inspect the spec unprompted?*
4. **Refine a shot** — "Pick the weakest frame and fix it with a note,
   e.g. 'lower angle, tighter, more fog'." ✓ New version appears
   reflecting the note; they find version history and compare.
   *Metric: refinements needed before they'd accept the shot (target ≤3).*
5. **Lock and watch it advance** — "Lock the shot you like best." ✓ They
   understand lock is final (immutable), and the status walks
   LOCKED → animatic-pending → animatic-ready without them doing anything.
   *Probe: "what do you think just happened?" — do they get the
   auto-trigger?*
6. **View and share the previs** — "Get the finished sequence to a
   collaborator." ✓ Sequence plays; they copy the share link; link opens
   in an incognito window.
   *Metric: total time from step 1 to playable previs (target: one
   session, no manual pipeline intervention).*

## Debrief (5 min)

- "Walk me through what Nova did with your scene, in your own words."
  (checks the mental model: shot list → spec → frame → lock → animatic)
- "What would you fix first?" / "What almost made you give up?"
- "Would you use this on a real project — at what stage?"
- Persona-specific: filmmaker — "would you trust the locked-frame
  provenance in a handoff?"; ad creator — "fast enough for a pitch?";
  student — "did the cinematography vocabulary teach or intimidate?"

## After each session

Sort observations into: must-fix (blocks a core step) / paper-cut /
backlog. Feed into 10.4 triage. Log time-to-previs and refine-count per
participant for 10.6 metric validation.
