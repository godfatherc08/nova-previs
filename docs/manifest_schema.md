# Provenance Manifest Schema (backlog 1.5)

Nova writes two manifest layers. This is deliberate and worth understanding
before reading `nova/storage/manifest.py`.

## 1. Genblaze's native run manifest

`genblaze_core.models.manifest.Manifest`, written by `ObjectStorageSink`
when a sink is attached to a pipeline run. It carries a canonical-JSON
SHA-256 (`canonical_hash`) over one run's steps and assets, and Genblaze
embeds SHA-256 provenance into output files natively. **Nova does not fork
or reimplement this** — it's confirmed-native (see `CLAUDE.md`).

Its limitation: it describes exactly one *run*. A shot's provenance spans
more than one run (spec authorship → N frame generations → the one locked
version), which is why Nova adds the second layer.

## 2. Nova's ShotManifest (written at lock, under Object Lock)

Per-shot chain-of-custody record at `locked/manifest.json`. It *references*
the Genblaze run manifest key rather than duplicating it.

```jsonc
{
  "schema_version": "nova-shot-manifest/1.0",
  "project_id": "…",
  "shot_id": "s3",
  "version": 2,
  "locked_at": "2026-07-18T…Z",
  "spec": { /* full ShotSpec — the exact IR that produced the frame */ },
  "frame": {
    "b2_key": "projects/…/shots/s3/locked/frame.png",
    "sha256": "<64 hex>",          // SHA-256 of the locked frame bytes
    "size_bytes": 812345,
    "media_type": "image/png"
  },
  "generation": {
    "provider": "google-nano-banana",
    "model": "gemini-2.5-flash-image",
    "prompt": "<the exact compiled prompt sent to the provider>",
    "params": { "aspect_ratio": "16:9" },
    "seed": null,                  // null for providers with no seed (nano-banana)
    "reference_keys": [ "projects/…/shots/s2/locked/frame.png" ]  // continuity
  },
  "genblaze_manifest_key": "…" | null,
  "manifest_sha256": "<64 hex>"    // seal — see below
}
```

### The two seals

`verify_shot_manifest` (and `scripts/verify_manifest.py`) check both:

1. **Manifest seal** — `manifest_sha256` is the SHA-256 of the manifest's
   canonical JSON (sorted keys, compact separators) with that field blanked.
   Recompute and compare. Editing *any* field — including the recorded
   `frame.sha256` — breaks this seal. This is the chain-of-custody property.
2. **Frame seal** — `frame.sha256` must equal the SHA-256 of the frame bytes
   in B2. Catches a swapped frame.

Both must hold for `report.ok`. A tamperer who edits the frame and updates
`frame.sha256` to match still fails seal (1).

### Why `seed` is often null

nano-banana's `generate_content` API neither accepts nor returns a seed
(verified against google-genai 2.11). For Gemini-generated frames,
reproducibility rests on the recorded prompt + reference frames, not a seed.
Providers that expose one (e.g. Flux via GMI Cloud) record it here.

## 3. SequenceManifest (backlog 7.3)

Written at `previs/manifest.json` on assembly. One entry per assembled shot,
in order, each carrying that shot's `manifest_sha256` — so the sequence
manifest chains back to every per-shot chain-of-custody record — plus the
SHA-256 of the assembled `sequence.mp4` and its own seal.

## Verification

```bash
python scripts/verify_manifest.py <project_id> <shot_id>      # fetch from B2
python scripts/verify_manifest.py --local manifest.json frame.png
```

Exit code 0 = chain intact, 1 = any tamper flag. Usable by a judge from a
fresh clone.
