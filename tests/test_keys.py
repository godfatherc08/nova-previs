"""Pure assertions on nova/storage/keys.py against the literal B2 layout
documented in CLAUDE.md ("B2 key structure"). No credentials needed."""

from nova.storage import keys


def test_scene_json_key():
    assert keys.scene_json_key("proj1") == "projects/proj1/scene.json"


def test_shot_spec_key():
    assert keys.shot_spec_key("proj1", "s1", 2) == "projects/proj1/shots/s1/spec/v2.json"


def test_frame_key():
    assert keys.frame_key("proj1", "s1", 1) == "projects/proj1/shots/s1/frames/v1.png"


def test_locked_frame_key():
    assert keys.locked_frame_key("proj1", "s1") == "projects/proj1/shots/s1/locked/frame.png"


def test_locked_manifest_key():
    assert (
        keys.locked_manifest_key("proj1", "s1")
        == "projects/proj1/shots/s1/locked/manifest.json"
    )


def test_animatic_clip_key():
    assert keys.animatic_clip_key("proj1", "s1") == "projects/proj1/shots/s1/animatic/clip.mp4"


def test_animatic_audio_key():
    assert (
        keys.animatic_audio_key("proj1", "s1") == "projects/proj1/shots/s1/animatic/audio.mp3"
    )


def test_previs_sequence_key():
    assert keys.previs_sequence_key("proj1") == "projects/proj1/previs/sequence.mp4"


def test_previs_manifest_key():
    assert keys.previs_manifest_key("proj1") == "projects/proj1/previs/manifest.json"


def test_take_key_lives_under_scratch_prefix():
    # Takes must live under scratch/ so the lifecycle rule (backlog 0.10)
    # can expire them — see design note in scripts/setup_b2_bucket.py.
    assert keys.take_key("proj1", "s1", "t1") == "scratch/proj1/s1/t1.png"


def test_parse_locked_frame_key_round_trips():
    key = keys.locked_frame_key("proj1", "s3")
    assert keys.parse_locked_frame_key(key) == ("proj1", "s3")


def test_parse_locked_frame_key_rejects_non_locked_paths():
    assert keys.parse_locked_frame_key(keys.frame_key("proj1", "s1", 1)) is None
    assert keys.parse_locked_frame_key(keys.locked_manifest_key("proj1", "s1")) is None
    assert keys.parse_locked_frame_key("projects/p/shots/s/locked/frame.png/extra") is None
    assert keys.parse_locked_frame_key("locked/frame.png") is None
    assert keys.parse_locked_frame_key("projects//shots/s/locked/frame.png") is None
