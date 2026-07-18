# Genblaze SDK feedback — issue drafts (backlog 11.5)

Two real defects/gaps hit during the Nova build, verified against installed
SDK source (`genblaze_core`, `genblaze_google` 0.3.1). Ready to file at
`github.com/backblaze-labs/genblaze/issues` — **not filed yet**; filing is
an external action, do it (or say the word) once wording is approved.
Filing at least one satisfies the Feedback Prize criterion.

---

## Issue 1 — bug: `ObjectStorageSink` can't upload local assets on Windows (`file://` path parsing)

**Title:** `_read_local_file` mis-parses `file://` URLs on Windows →
FileNotFoundError on every local-asset upload

**Body:**

`genblaze_core/storage/transfer.py::_read_local_file` resolves file URLs
with `Path(unquote(urlparse(url).path))`. On Windows, a correct RFC-8089
URI like `file:///C:/work/frame.png` has `urlparse(...).path` =
`/C:/work/frame.png`; `Path()` of that becomes the drive-*relative* path
`C:work\frame.png` (note: no root), so the read raises
`FileNotFoundError` and `ObjectStorageSink` cannot upload any locally
generated asset on Windows. Linux is unaffected.

Related: `genblaze_google` builds its asset URIs as
`f"file://{quote(path)}"`, which percent-escapes the drive colon and
backslashes into the URL *netloc* — invalid on Windows even before the
read-side bug.

**One-line fix:** use the stdlib inverse designed for this —
`urllib.request.url2pathname(urlparse(url).path)` — instead of
`Path(unquote(...))`; and emit URIs with `Path.as_uri()` rather than
string-formatting. We use exactly this pattern in our own provider adapter
(Nova, Backblaze GenAI hackathon) and it round-trips on Windows and Linux.

Repro (Windows):

```python
from genblaze_core.storage.transfer import _read_local_file
from pathlib import Path
p = Path(r"C:\work\frame.png")  # exists
_read_local_file(p.as_uri())    # FileNotFoundError: C:work\frame.png
```

---

## Issue 2 — gap: no provider path to Gemini image models (nano-banana); `ImagenProvider` silently mismatches

**Title:** `genblaze-google` `ImagenProvider` can't serve
`gemini-2.5-flash-image`, and preflight doesn't catch the mismatch

**Body:** Three compounding findings from wiring
`gemini-2.5-flash-image` ("nano-banana") as a primary image model:

1. `ImagenProvider.generate()` calls `client.models.generate_images()` —
   the Imagen API. Gemini image models are served via
   `generate_content(response_modalities=["IMAGE"])`, a different surface;
   Gemini slugs fail at the wire call.
2. `GOOGLE_IMAGEN_FAMILY` matches `^imagen-` only, so a Gemini slug falls
   through to the permissive `*` fallback spec — preflight passes and the
   user gets a late, opaque provider error instead of an early "model not
   supported by this provider."
3. `ImagenProvider.get_capabilities()` declares `supported_inputs=["text"]`
   and `accepts_chain_input=False` — no reference-image input at all, which
   rules it out for any consistency/continuity workflow even where the slug
   works.

**Suggestions:** (a) a `GeminiImageProvider` in `genblaze-google` targeting
`generate_content` with image inputs + `accepts_chain_input=True`; (b) make
the registry's fallback behavior configurable or warn when a slug misses
every family pattern for the chosen provider. We built (a) as an external
`SyncProvider` adapter (public extension point — that part worked great and
is a genuinely good API), happy to share our implementation as a reference.
