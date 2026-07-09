# Nova

AI-powered cinematic previsualization. Describe a scene in plain language;
Nova breaks it into a shot list, generates a controllable storyboard frame
per shot, compiles locked shots into animatic clips with scratch audio, and
assembles a previs sequence. Full product spec: [`Nova_PRD.md`](Nova_PRD.md).
Backlog: [`Nova_Backlog.csv`](Nova_Backlog.csv).

Built for the Backblaze Generative AI Media Hackathon (submission window:
June 22 – Aug 3, 2026), orchestrated through [Genblaze](https://github.com/backblaze-labs/genblaze)
and persisted on Backblaze B2.

## Tech stack

Decision for backlog task 0.4. Rationale below; see `Nova_PRD.md` §9.6 for
the underlying Genblaze SDK audit (task 0.3) that some of this leans on.

### Backend — FastAPI (Python)

Backend language was already fixed by the project's dependency on
`genblaze-core` (Python-only SDK). FastAPI specifically because:

- Async-native, which the B2 webhook handler needs — it must ACK within
  B2's 3-second delivery window, then run the animatic stage in the
  background (`BackgroundTasks`). No Redis/Celery needed at this scale;
  the trade-off (in-process background work is lost on a mid-task
  restart) is covered by B2's at-least-once redelivery + the webhook
  handler's required idempotency check + the task 5.3 polling fallback.
- Typed request/response models map directly onto the Shot Spec and
  provenance manifest schemas already defined in the PRD.
- Can serve the built frontend as static files from the same process
  (see hosting, below) — one deployable, one URL.

### Frontend — React + Vite + TypeScript

- **Vite over Next.js**: no SSR/SEO need — Nova is a tool behind a shared
  link, not a marketing site — so a plain SPA is enough. Vite's static
  build gets mounted directly into the FastAPI app via `StaticFiles`,
  which collapses frontend + backend into one deployable process: no
  CORS setup, one uptime surface to babysit through judging.
- **shadcn/ui + Tailwind** for the component set — fast to assemble the
  required screens (scene input, shot list editor, storyboard grid,
  refine panel, version scrub, lock/status indicators, previs viewer).
- **TanStack Query** for server-state fetching and polling. Shot status
  (`DRAFT → REFINING → LOCKED → ANIMATIC_PENDING → ANIMATIC_READY →
  ASSEMBLED`) is polled every 2–3s — simpler and more reliable to ship
  in a hackathon than SSE/WebSockets. SSE is a reasonable upgrade later
  if time allows, not required for MVP.
- **@dnd-kit** for shot list reordering — the maintained alternative to
  the abandoned `react-beautiful-dnd`.

### Data — Postgres (managed via host) + SQLAlchemy

B2 stays the source of truth for durable artifacts (frames, specs,
manifests, clips, sequences) per the PRD — that doesn't change. But shot
and project *state* (the state machine in the PRD, which must be tracked
explicitly rather than inferred from file existence) needs a row store
with transactional updates, since B2 webhook delivery is at-least-once
and concurrent status writes must not race. SQLite locally for dev speed;
the host's managed Postgres in production so state survives redeploys —
same SQLAlchemy models either way, just a different connection string.

### Hosting — Render, paid Starter tier (~$7/mo)

One always-on web service running the FastAPI app (API + webhook +
static frontend build) plus Render's managed Postgres add-on.

**Deliberate deviation from "free," flagged explicitly:** Render's (and
Railway's) free tiers spin the service down after ~15 minutes idle. A B2
event notification landing during a cold spin-up risks missing the
3-second delivery window on the first attempt. B2 retries, the handler
is idempotent, and the task 5.3 polling fallback exists too — so the
free tier would probably still work end-to-end. But Nova's pitch leans
on reliability/reproducibility (PRD §12), and the judges are Backblaze
engineers scoring exactly that axis, so ~$7/mo to remove a visible
cold-start risk during the live judging window is worth it. If budget is
a hard constraint, Fly.io's small always-on shared-CPU VM (~$2–3/mo) is
an equivalent alternative for the same reason.

## Setup

Requires Python 3.11+ (matches Genblaze's minimum).

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env           # then fill in keyID / applicationKey from
                                # the Backblaze B2 console (App Keys)
```

Run the test suite:

```bash
pytest -v
```

B2-hitting tests (`tests/test_b2_connection.py`, `tests/test_b2_bucket_setup.py`)
skip automatically if `.env` isn't populated — expected in CI until
`B2_KEY_ID` / `B2_APPLICATION_KEY` repo secrets are configured.

The `nova-previs` bucket (PRD §8.2 layout, Object Lock enabled, `scratch/`
lifecycle rule) is provisioned by `scripts/setup_b2_bucket.py` — safe to
re-run, it skips creation if the bucket already exists:

```bash
python scripts/setup_b2_bucket.py
```

**Windows note:** if you hit `SSLCertVerificationError` talking to B2,
it's very likely AV software (Avast/AVG Web Shield, etc.) doing HTTPS
inspection with a root CA that OpenSSL 3.x's strict parser rejects. This
repo depends on `truststore` to route verification through the OS trust
store instead, which resolves it — no extra config needed, just make
sure `requirements.txt` is installed.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs `ruff check` and
`pytest` on every push/PR to `main`.
