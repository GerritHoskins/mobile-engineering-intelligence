"""Record real vendor responses as test fixtures by running a normal ingest
through a recording transport (read-only towards the vendors; writes the DB).

    uv run python -m app.connectors.record --org demo

Responses are scrubbed of emails, account ids, display names and self/avatar
URLs before being written to tests/fixtures/vendors/<org>/.
"""

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.connectors.http import RecordingTransport
from app.ingest import ingest

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "vendors"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", required=True)
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()

    directory = FIXTURES / args.org
    shutil.rmtree(directory, ignore_errors=True)  # a recording is always a complete, consistent set
    end = datetime.now(timezone.utc).replace(microsecond=0)
    ingest(args.org, args.days, transport=RecordingTransport(directory), end=end)
    (directory / "_window.json").write_text(json.dumps({"end": end.isoformat(), "days": args.days}, indent=1))
    print(f"recorded {len(list(directory.glob('*.json'))) - 1} responses to {directory}")


if __name__ == "__main__":
    main()
