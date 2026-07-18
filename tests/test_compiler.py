"""
Backlog 3.1 (compiler half): a Shot Spec compiles to a prompt that actually
carries its cinematography.

The point of these tests is not that *some* string comes out — it's that the
numeric/enum cinematography in the IR survives the translation. If a field of
the Shot Spec can change without changing the prompt, that field is decorative
and the compiler is lying about being controllable.
"""

import pytest

from nova.agent.compiler import DEFAULT_ASPECT_RATIO, build_prompt, compile_shot
from nova.models.shot_spec import (
    Camera,
    Framing,
    Grade,
    Lens,
    Lighting,
    ShotSpec,
    Subject,
)


def _spec(**overrides) -> ShotSpec:
    base = {
        "shot_id": "s3",
        "version": 2,
        "intent": "reveal the scale of the drone swarm above the ruined skyline",
        "camera": Camera(angle="low", height_m=1.2, movement="slow push-in"),
        "lens": Lens(focal_length_mm=18, aperture_f=2.8),
        "framing": Framing(shot_size="extreme wide", composition="rule-of-thirds, subject lower-left"),
        "lighting": Lighting(key="low-key", mood="dramatic shadows", practicals=["drone lights"]),
        "grade": Grade(look="desaturated teal", contrast="high"),
        "subject": Subject(primary="woman in tattered coat", blocking="walking left-to-right, foreground"),
        "world": ["destroyed buildings", "airborne drones", "dense fog"],
    }
    base.update(overrides)
    return ShotSpec(**base)


def test_prompt_carries_every_load_bearing_spec_field():
    prompt = build_prompt(_spec())

    # Subject, blocking, world, composition, mood, practicals, grade, intent
    # all reach the model verbatim.
    assert "woman in tattered coat" in prompt
    assert "walking left-to-right, foreground" in prompt
    assert "destroyed buildings" in prompt
    assert "dense fog" in prompt
    assert "rule-of-thirds, subject lower-left" in prompt
    assert "dramatic shadows" in prompt
    assert "drone lights" in prompt
    assert "desaturated teal" in prompt
    assert "drone swarm" in prompt

    # Enums are translated to language, not passed through as bare tokens.
    assert "extreme wide shot" in prompt
    assert "low-angle shot" in prompt
    assert "low-key lighting" in prompt
    assert "high-contrast grade" in prompt

    # Previs, not a photograph.
    assert "previsualization storyboard frame" in prompt


def test_lens_numbers_compile_to_perceptual_language():
    """The core claim of the compiler: an image model can't read '18mm f/2.8',
    so the compiler must derive what those numbers *do* to the frame."""
    wide_fast = build_prompt(_spec(lens=Lens(focal_length_mm=18, aperture_f=1.8)))
    assert "wide-angle lens" in wide_fast
    assert "very shallow depth of field" in wide_fast

    long_slow = build_prompt(_spec(lens=Lens(focal_length_mm=300, aperture_f=16)))
    assert "long telephoto lens" in long_slow
    assert "deep focus" in long_slow

    # The raw numbers still ride along for the manifest/record.
    assert "18mm" in wide_fast
    assert "f/1.8" in wide_fast


@pytest.mark.parametrize(
    ("angle", "expected"),
    [
        ("low", "looking up"),
        ("high", "looking down"),
        ("overhead", "bird's-eye"),
        ("dutch", "horizon tilts"),
        ("worms-eye", "worm's-eye"),
        ("over-the-shoulder", "over-the-shoulder"),
        ("eye-level", "eye level"),
    ],
)
def test_every_camera_angle_enum_has_a_distinct_phrasing(angle, expected):
    """Closed enums exist so this mapping is total. A missing key here would
    be a KeyError at generation time, not a silently vague prompt."""
    prompt = build_prompt(_spec(camera=Camera(angle=angle, height_m=1.5, movement="static")))
    assert expected in prompt


def test_changing_one_enum_changes_exactly_that_clause():
    """What makes the refine loop (3.6) feel like a control surface rather
    than a reroll: one field changed => one clause changed."""
    before = build_prompt(_spec(grade=Grade(look="desaturated teal", contrast="low")))
    after = build_prompt(_spec(grade=Grade(look="desaturated teal", contrast="high")))

    assert before != after
    differing = [
        (b, a)
        for b, a in zip(before.split(". "), after.split(". "), strict=True)
        if b != a
    ]
    assert len(differing) == 1
    assert "contrast" in differing[0][0]


def test_static_camera_omits_the_movement_clause():
    """A static shot has no move to be 'the opening frame of' — saying so
    anyway just spends tokens telling the model to do nothing."""
    assert "opening frame" not in build_prompt(
        _spec(camera=Camera(angle="eye-level", height_m=1.5, movement="static"))
    )
    assert "opening frame" in build_prompt(
        _spec(camera=Camera(angle="eye-level", height_m=1.5, movement="slow push-in"))
    )


def test_compile_shot_emits_aspect_ratio_param():
    compiled = compile_shot(_spec())
    assert compiled.params["aspect_ratio"] == DEFAULT_ASPECT_RATIO
    assert compiled.reference_keys == []


def test_continuity_refs_resolve_to_locked_frame_b2_keys():
    """continuity_refs are short ('s1_frame'); the provider needs real keys.
    They must resolve through storage/keys.py to the exact locked/frame.png
    path the lock webhook (5.2) matches on."""
    compiled = compile_shot(
        _spec(continuity_refs=["s1_frame", "s2_frame"]),
        project_id="proj123",
    )
    assert compiled.reference_keys == [
        "projects/proj123/shots/s1/locked/frame.png",
        "projects/proj123/shots/s2/locked/frame.png",
    ]


def test_continuity_refs_without_project_id_fail_loudly():
    """Refs resolve to project-scoped keys. Silently dropping them would
    silently drop cross-shot continuity — the one thing CLAUDE.md says not
    to lose."""
    with pytest.raises(ValueError, match="project_id"):
        compile_shot(_spec(continuity_refs=["s1_frame"]))
