"""Guard for committed vendor recordings: no personal email addresses.

The only address allowed is the demo commit identity (a reserved .invalid
domain). Anything else means the scrubber missed a field -- fix SCRUB_KEYS in
app/connectors/http.py and re-record, don't allowlist it here."""

import re
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "vendors"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")  # letter TLD: not release names like app@1.2.0
ALLOWED = re.compile(r"@[\w.-]+\.invalid$")


def test_recordings_contain_no_email_addresses() -> None:
    offenders = {
        f"{path.relative_to(FIXTURES)}: {address}"
        for path in FIXTURES.rglob("*.json")
        for address in EMAIL.findall(path.read_text())
        if not ALLOWED.search(address)
    }
    assert not offenders, sorted(offenders)
