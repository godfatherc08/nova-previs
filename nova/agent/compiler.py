"""
Backlog 3.1: Shot Spec -> provider-specific prompt + params (CLAUDE.md
module layout: "the highest-leverage file in the repo").

Why this file exists at all: the Shot Spec is a *model-agnostic* IR of real
cinematography — ``lens.focal_length_mm: 18``, ``aperture_f: 2.8``,
``camera.angle: "low"``. No image model consumes that. They consume prose.
The compiler is the one place that translation happens, and it is where
Nova's actual leverage over "type a prompt into an image model" lives:

  * **Numeric -> perceptual.** An 18mm f/2.8 lens means nothing to a
    diffusion model as a number, but "wide-angle lens, expansive perspective
    with slight edge distortion, moderately shallow depth of field" does.
    ``_lens_phrase`` derives those perceptual consequences from the numbers
    rather than passing the numbers through and hoping.
  * **Closed enums -> stable language.** The Shot Spec's categorical fields
    (angle, shot size, lighting key, contrast) are closed enums precisely so
    this mapping can be a deterministic lookup instead of fuzzy string
    matching (see models/shot_spec.py). Same enum always compiles to the
    same phrasing, so a refine that changes *one* field changes exactly one
    clause of the prompt — which is what makes the refine loop (backlog 3.6)
    feel controllable instead of a reroll.

The prompt body is deliberately provider-neutral prose: nano-banana (3.2),
gpt-image-1 and Flux (3.3) all take a text prompt, and a fallback must not
silently change the *content* of the request. Provider-specific bits are
confined to ``params`` (see ``compile_shot``'s ``target``).

Ordering matters: the clauses run subject -> world -> framing -> lens ->
lighting -> grade, i.e. most to least semantically load-bearing, because
image models weight earlier tokens more heavily. The style anchor leads so
the whole frame is pinned as previs, not as a photograph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from nova.models.shot_spec import CameraAngle, Contrast, LightingKey, ShotSize, ShotSpec
from nova.storage import keys

# Target providers the compiler can emit params for. The *prompt* is the same
# across all of them by design (see module docstring) — only params differ.
CompileTarget = Literal["nano-banana", "gpt-image-1", "flux"]

DEFAULT_ASPECT_RATIO = "16:9"

# Previs frames are storyboard art, not finished photography. Without this
# anchor the models drift toward photoreal stock imagery, which reads as a
# *result* rather than a *plan* and misleads everyone downstream in the
# filmmaking process about how locked the look is.
_STYLE_ANCHOR = (
    "Cinematic previsualization storyboard frame, film still, "
    "photorealistic lighting and staging, no text, no watermark, "
    "no UI overlays, no border"
)

_ANGLE_PHRASES: dict[CameraAngle, str] = {
    "eye-level": "camera at eye level with the subject, neutral and observational",
    "low": "low-angle shot, camera below the subject looking up, making the subject loom",
    "high": "high-angle shot, camera above the subject looking down, diminishing the subject",
    "overhead": "directly overhead top-down bird's-eye shot",
    "dutch": "dutch angle, camera canted so the horizon tilts, uneasy and destabilized",
    "worms-eye": "worm's-eye view from ground level looking almost straight up",
    "over-the-shoulder": "over-the-shoulder shot, framed past a foreground figure's shoulder",
}

_SHOT_SIZE_PHRASES: dict[ShotSize, str] = {
    "extreme wide": "extreme wide shot, the subject small within a vast environment",
    "wide": "wide shot, full environment visible around the subject",
    "full": "full shot, subject framed head to toe",
    "medium wide": "medium wide shot, subject framed from the knees up",
    "medium": "medium shot, subject framed from the waist up",
    "medium close-up": "medium close-up, subject framed from the chest up",
    "close-up": "close-up, subject's face filling most of the frame",
    "extreme close-up": "extreme close-up, a single detail filling the frame",
    "insert": "insert shot, isolated detail of an object or action",
}

_LIGHTING_PHRASES: dict[LightingKey, str] = {
    "high-key": "high-key lighting, bright and evenly lit with soft, open shadows",
    "low-key": "low-key lighting, predominantly dark with deep shadow and selective highlights",
    "flat": "flat, diffuse lighting with minimal shadow modelling",
    "natural": "naturalistic available light, motivated by the environment",
    "chiaroscuro": "chiaroscuro lighting, hard-edged pools of light carved out of darkness",
}

_CONTRAST_PHRASES: dict[Contrast, str] = {
    "low": "low-contrast grade, lifted blacks, gentle tonal range",
    "medium": "medium contrast, natural tonal range",
    "high": "high-contrast grade, crushed blacks and bright highlights",
}


def _lens_phrase(focal_length_mm: float, aperture_f: float) -> str:
    """Translate a focal length + f-stop into their perceptual consequences.

    Image models don't reason about optics numerically, so passing "18mm
    f/2.8" through as digits mostly wastes tokens. What actually changes the
    render is the *effect*: field of view, perspective distortion, and depth
    of field. The numbers are still carried in the Shot Spec (and into the
    manifest) — this is purely the prompt-facing translation.
    """
    if focal_length_mm <= 24:
        field_of_view = "wide-angle lens, expansive field of view, exaggerated depth and mild edge distortion"
    elif focal_length_mm <= 45:
        field_of_view = "normal lens, perspective close to human vision"
    elif focal_length_mm <= 85:
        field_of_view = "short telephoto lens, mildly compressed perspective, flattering on faces"
    elif focal_length_mm <= 200:
        field_of_view = "telephoto lens, compressed perspective stacking foreground and background"
    else:
        field_of_view = "long telephoto lens, extreme compression, background stacked hard against the subject"

    if aperture_f <= 2.0:
        depth_of_field = "very shallow depth of field, subject isolated against a soft blurred background"
    elif aperture_f <= 4.0:
        depth_of_field = "shallow depth of field, background softly out of focus"
    elif aperture_f <= 8.0:
        depth_of_field = "moderate depth of field, background legible but soft"
    else:
        depth_of_field = "deep focus, foreground and background both sharp"

    return (
        f"shot on a {focal_length_mm:g}mm lens at f/{aperture_f:g} — "
        f"{field_of_view}, {depth_of_field}"
    )


@dataclass(frozen=True)
class CompiledShot:
    """What the image stage actually sends to a provider."""

    prompt: str
    params: dict = field(default_factory=dict)
    # Full B2 keys of prior *locked* frames to pass as reference images.
    # Resolved from the Shot Spec's short ``s1_frame`` refs at compile time,
    # per CLAUDE.md ("Resolved to full B2 keys at compile time"). Fetching
    # these and attaching them to the call is backlog 3.4 — the compiler's
    # job ends at resolution.
    reference_keys: list[str] = field(default_factory=list)


def resolve_continuity_refs(spec: ShotSpec, project_id: str) -> list[str]:
    """Turn ``["s1_frame"]`` into full ``locked/frame.png`` B2 keys.

    Built through ``storage/keys.py`` rather than string-formatted here —
    CLAUDE.md makes that a hard rule, since the lock webhook (backlog 5.2)
    matches on the exact ``locked/frame.png`` suffix.
    """
    return [
        keys.locked_frame_key(project_id, ref.removesuffix("_frame"))
        for ref in spec.continuity_refs
    ]


def build_prompt(spec: ShotSpec) -> str:
    """Compile a Shot Spec into provider-neutral prompt prose.

    Deliberately not provider-specific: a fallback (backlog 3.3) swapping
    nano-banana for Flux must change *how* the frame is rendered, never
    *what* was asked for.
    """
    clauses: list[str] = [_STYLE_ANCHOR]

    # Subject and blocking first — the load-bearing content of the frame.
    clauses.append(f"Subject: {spec.subject.primary}, {spec.subject.blocking}")

    if spec.world:
        clauses.append(f"Environment: {', '.join(spec.world)}")

    clauses.append(_SHOT_SIZE_PHRASES[spec.framing.shot_size])
    clauses.append(_ANGLE_PHRASES[spec.camera.angle])
    clauses.append(f"camera roughly {spec.camera.height_m:g}m above the ground")
    clauses.append(f"Composition: {spec.framing.composition}")

    clauses.append(_lens_phrase(spec.lens.focal_length_mm, spec.lens.aperture_f))

    lighting = _LIGHTING_PHRASES[spec.lighting.key]
    if spec.lighting.mood:
        lighting = f"{lighting}, {spec.lighting.mood}"
    if spec.lighting.practicals:
        lighting = f"{lighting}; visible practical light sources: {', '.join(spec.lighting.practicals)}"
    clauses.append(lighting)

    clauses.append(f"Color grade: {spec.grade.look}, {_CONTRAST_PHRASES[spec.grade.contrast]}")

    # Camera movement describes a move across time, which a still frame
    # cannot show. It's included anyway, framed explicitly as "the opening
    # frame of" the move, because it changes where the subject sits in frame
    # at the start of the shot (a push-in starts looser than it ends). The
    # same field is what actually drives motion in the animatic stage (6.1).
    if spec.camera.movement and spec.camera.movement.lower() != "static":
        clauses.append(f"Framed as the opening frame of a {spec.camera.movement} camera move")

    # Intent last: not a visual instruction, but it gives the model the
    # narrative point of the shot to arbitrate ambiguity against.
    clauses.append(f"Narrative intent: {spec.intent}")

    return ". ".join(clauses) + "."


def compile_shot(
    spec: ShotSpec,
    *,
    project_id: str | None = None,
    target: CompileTarget = "nano-banana",
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
) -> CompiledShot:
    """Compile a Shot Spec into a provider call.

    ``project_id`` is only needed to resolve ``continuity_refs`` into B2
    keys; a spec with no refs compiles fine without it.
    """
    if spec.continuity_refs and project_id is None:
        raise ValueError(
            f"shot {spec.shot_id!r} has continuity_refs {spec.continuity_refs} but no "
            "project_id was passed — refs resolve to project-scoped B2 keys"
        )

    prompt = build_prompt(spec)
    reference_keys = resolve_continuity_refs(spec, project_id) if project_id else []

    # Params are the only provider-specific surface. Today every target takes
    # an aspect ratio and nothing else Nova needs to set; the branch exists so
    # backlog 3.3 has an obvious seam to hang gpt-image-1 / Flux params on
    # (size strings, guidance scale) without touching the prompt path.
    params: dict
    if target == "gpt-image-1":
        # gpt-image-* takes discrete size strings, not free aspect ratios —
        # 1536x1024 is its landscape size, the closest to previs 16:9
        # (verified against the installed genblaze_openai dalle.py
        # ``_ImageModelSpec.fixed_sizes`` for gpt-image-1).
        params = {"size": "1536x1024"}
    else:
        params = {"aspect_ratio": aspect_ratio}

    return CompiledShot(prompt=prompt, params=params, reference_keys=reference_keys)


def compile_refine(
    spec: ShotSpec,
    instruction: str,
    *,
    project_id: str | None = None,
    target: CompileTarget = "nano-banana",
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
) -> CompiledShot:
    """Compile a refinement into an *edit-in-place* provider call (backlog 3.6).

    Different from ``compile_shot`` by design (CLAUDE.md: "don't reuse run()
    ... the prompt construction differs"): the prior frame rides along as an
    input image, and the prompt leads with an edit instruction anchored to
    that image, so the model treats the request as "change this frame" rather
    than "imagine a new one". The full re-compiled spec prose follows as the
    ground truth the edited frame must still satisfy — that's what keeps a
    refine from drifting fields the user didn't touch.
    """
    base = compile_shot(
        spec, project_id=project_id, target=target, aspect_ratio=aspect_ratio
    )
    prompt = (
        "Edit the provided storyboard frame. Apply exactly this change: "
        f"{instruction}. Preserve the character identity, environment, and "
        "every aspect of the composition the change does not require touching. "
        f"The edited frame must match this full shot description: {base.prompt}"
    )
    return CompiledShot(prompt=prompt, params=base.params, reference_keys=base.reference_keys)


def build_motion_prompt(spec: ShotSpec) -> str:
    """Compile the Shot Spec's *temporal* fields into a video-model prompt
    (backlog 6.1). The locked frame supplies composition, subject, lighting
    and grade — the video model's job is only to move the camera and the
    subject, so the prompt speaks almost entirely in motion terms and
    re-describes the frame as little as possible (re-description invites
    drift from the locked look).
    """
    movement = spec.camera.movement or "static"
    clauses = [
        f"Cinematic previs animatic from this exact frame, {movement} camera move",
        f"subject: {spec.subject.primary}, {spec.subject.blocking}",
        "hold the frame's existing composition, lighting, and color grade",
        f"mood: {spec.lighting.mood}",
        f"narrative intent: {spec.intent}",
    ]
    return ". ".join(clauses) + "."


def build_audio_prompt(spec: ShotSpec) -> str:
    """Compile the Shot Spec's atmosphere into a scratch-audio prompt
    (backlog 6.3). Scratch ambient/score, not sound design: it sells the
    mood of the previs, so it leans on lighting mood, world elements, and
    intent rather than literal foley of every object.
    """
    clauses = [f"Cinematic ambient scratch track, {spec.lighting.mood} mood"]
    if spec.world:
        clauses.append(f"environment: {', '.join(spec.world[:5])}")
    clauses.append(f"tone: {spec.grade.look}")
    clauses.append(f"scene: {spec.intent}")
    return ". ".join(clauses) + "."
