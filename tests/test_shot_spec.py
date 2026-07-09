"""
Backlog 1.1 acceptance criteria: the Shot Spec schema validates against the
exact example instance in PRD §6. No B2 credentials needed — pure schema
test, always runs in CI.
"""

import pytest
from pydantic import ValidationError

from nova.models.shot_spec import ShotSpec

# Verbatim from Nova_PRD.md §6, plus "version": 2 to match the fuller
# example in CLAUDE.md's "Shot Spec schema" section (the technical model
# CLAUDE.md documents includes version; the PRD's illustrative example
# omits it for readability — this test reconciles the two).
PRD_SECTION_6_EXAMPLE = {
    "shot_id": "s3",
    "version": 2,
    "intent": "reveal the scale of the drone swarm above the ruined skyline",
    "camera": {"angle": "low", "height_m": 1.2, "movement": "slow push-in"},
    "lens": {"focal_length_mm": 18, "aperture_f": 2.8},
    "framing": {"shot_size": "extreme wide", "composition": "rule-of-thirds, subject lower-left"},
    "lighting": {"key": "low-key", "mood": "dramatic shadows", "practicals": ["drone lights"]},
    "grade": {"look": "desaturated teal", "contrast": "high"},
    "subject": {"primary": "woman in tattered coat", "blocking": "walking left-to-right, foreground"},
    "world": ["destroyed buildings", "dumped cars", "airborne drones", "dense fog"],
    "continuity_refs": ["s1_frame", "s2_frame"],
}


def test_prd_section_6_example_validates():
    spec = ShotSpec.model_validate(PRD_SECTION_6_EXAMPLE)
    assert spec.shot_id == "s3"
    assert spec.version == 2
    assert spec.camera.angle == "low"
    assert spec.continuity_refs == ["s1_frame", "s2_frame"]


def test_round_trips_through_json():
    spec = ShotSpec.model_validate(PRD_SECTION_6_EXAMPLE)
    reparsed = ShotSpec.model_validate_json(spec.model_dump_json())
    assert reparsed == spec


def test_version_defaults_to_1():
    payload = {k: v for k, v in PRD_SECTION_6_EXAMPLE.items() if k != "version"}
    spec = ShotSpec.model_validate(payload)
    assert spec.version == 1


@pytest.mark.parametrize(
    "field, bad_value",
    [
        ("camera", {"angle": "wide-ish", "height_m": 1.2, "movement": "push-in"}),  # not a real enum value
        ("lens", {"focal_length_mm": 4, "aperture_f": 2.8}),  # focal length below the 8mm floor
        ("framing", {"shot_size": "super wide", "composition": "centered"}),  # not a real enum value
    ],
)
def test_rejects_invalid_categorical_and_range_values(field, bad_value):
    payload = dict(PRD_SECTION_6_EXAMPLE)
    payload[field] = bad_value
    with pytest.raises(ValidationError):
        ShotSpec.model_validate(payload)


def test_rejects_unknown_top_level_field():
    payload = dict(PRD_SECTION_6_EXAMPLE)
    payload["director_notes"] = "not part of the schema"
    with pytest.raises(ValidationError):
        ShotSpec.model_validate(payload)


def test_rejects_malformed_continuity_ref():
    payload = dict(PRD_SECTION_6_EXAMPLE)
    payload["continuity_refs"] = ["s1"]  # missing the "_frame" suffix
    with pytest.raises(ValidationError):
        ShotSpec.model_validate(payload)


def test_rejects_self_referencing_continuity_ref():
    payload = dict(PRD_SECTION_6_EXAMPLE)
    payload["continuity_refs"] = ["s3_frame"]  # shot_id is "s3" — can't reference itself
    with pytest.raises(ValidationError):
        ShotSpec.model_validate(payload)


def test_rejects_unsafe_shot_id_for_b2_key_use():
    payload = dict(PRD_SECTION_6_EXAMPLE)
    payload["shot_id"] = "s3/../escape"
    with pytest.raises(ValidationError):
        ShotSpec.model_validate(payload)
