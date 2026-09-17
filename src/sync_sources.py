"""CLI entry point: sync every configured source's cameras into the database.

    python .\\sync_sources.py
    python .\\sync_sources.py --sources tfl
"""

import argparse
import logging

from pipeline import MasterPipeline
from sources import AVAILABLE_SOURCES, load_sources


def main():

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Retries on connection resets are expected at this concurrency and are
    # already handled by each source's session - don't spam the console.
    logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

    parser = argparse.ArgumentParser(
        description="Sync all configured camera sources into the OpenHighways database."
    )

    parser.add_argument(
        "--sources",
        help=f"Comma-separated sources to run (choices: {', '.join(AVAILABLE_SOURCES)}). Default: all.",
        default=None,
    )

    args = parser.parse_args()

    names = [name.strip() for name in args.sources.split(",")] if args.sources else None

    results = MasterPipeline(load_sources(names)).run()

    for result in results:

        if result.status == "ok":
            print(
                f"[OK] {result.source}: {result.camera_count} cameras "
                f"({result.deactivated_count} marked inactive)"
            )
        else:
            print(f"[FAILED] {result.source}: {result.error}")


if __name__ == "__main__":
    main()
