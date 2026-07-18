"""
Backlog 5.3: run the polling fallback as a standalone loop.

Keeps the pipeline advancing end-to-end when the B2 event path is disabled
or unreachable (local dev with no public URL, or a lost delivery). The
same logic also retries shots whose animatic stage failed.

    python scripts/run_poller.py            # loop every 30s
    python scripts/run_poller.py --once     # single pass (cron-friendly)
"""

import argparse
import logging
import time

from dotenv import load_dotenv

load_dotenv()

from nova.models.project import init_db
from nova.pipeline.advance import poll_locked_shots

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="single pass, then exit")
    parser.add_argument("--interval", type=float, default=30.0)
    ns = parser.parse_args()

    init_db()
    while True:
        advanced = poll_locked_shots()
        if advanced:
            logging.info("advanced: %s", advanced)
        if ns.once:
            break
        time.sleep(ns.interval)


if __name__ == "__main__":
    main()
