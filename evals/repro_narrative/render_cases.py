"""Render the eval's input set as one HTML page for review.

    uv run python -m evals.repro_narrative.render_cases [out.html]
"""

import html
import json
import sys
from collections import Counter
from pathlib import Path

from evals.repro_narrative.build_cases import CASES_DIR

DEFAULT_OUT = Path(".claude/hillclimb/repro_narrative/inputs.html")

CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--muted:#6e6e73;--card:#f5f5f7;--line:#d2d2d7;--chip:#e8eefc;--chipfg:#1f3a8a;
--real:#e6f4ea;--realfg:#1e6b34}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111;--fg:#eee;--muted:#999;--card:#1c1c1e;
--line:#333;--chip:#1e2a4a;--chipfg:#b8c8ff;--real:#16301f;--realfg:#9fe0b0}}
:root[data-theme="dark"]{--bg:#111;--fg:#eee;--muted:#999;--card:#1c1c1e;--line:#333;--chip:#1e2a4a;--chipfg:#b8c8ff;
--real:#16301f;--realfg:#9fe0b0}
body{background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,system-ui,sans-serif;margin:0;padding:24px 16px;
max-width:1100px;margin-inline:auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:0}
.muted{color:var(--muted)}section{border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:16px 0;
background:var(--card)}.chip{display:inline-block;background:var(--chip);color:var(--chipfg);border-radius:999px;
padding:1px 8px;margin:2px 3px 2px 0;font-size:12px}.chip.real{background:var(--real);color:var(--realfg)}
table{border-collapse:collapse;width:100%;margin-top:10px;font-size:13px}td{border-top:1px solid var(--line);
padding:4px 6px;vertical-align:top}td:first-child{white-space:nowrap;font-family:ui-monospace,monospace;width:1%}
code{font-family:ui-monospace,monospace;font-size:12px;word-break:break-word}
.summary td{border:none;padding:1px 8px 1px 0}
"""


def _row(item: dict) -> str:
    rest = {k: v for k, v in item.items() if k != "id"}
    return f"<tr><td>{html.escape(item['id'])}</td><td><code>{html.escape(json.dumps(rest, default=str))}</code></td></tr>"


def render(out: Path) -> None:
    cases = [json.loads(p.read_text()) for p in sorted(CASES_DIR.glob("*.json"))]
    coverage = Counter(c for case in cases for c in case["covers"] if not c.startswith(("precondition:", "varies:")))
    parts = [f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'>"
             f"<title>Repro narrative inputs</title><style>{CSS}</style></head><body>",
             f"<h1>Reproduction-narrative eval: {len(cases)} input packets</h1>",
             "<p class=muted>Each packet is exactly what the model sees (built by build_reproduction → repro_packet). "
             "Green = frozen from the live demo accounts; blue = synthetic incident run through the same code.</p>",
             "<table class=summary>" + "".join(f"<tr><td>{n}</td><td>{html.escape(k)}</td></tr>"
                                               for k, n in sorted(coverage.items())) + "</table>"]
    for case in cases:
        chip = f"<span class='chip{' real' if case['source'] == 'real' else ''}'>{case['source']}</span>"
        chips = "".join(f"<span class=chip>{html.escape(c)}</span>" for c in case["covers"]
                        if not c.startswith(("precondition:", "varies:")))
        parts.append(f"<section><h2>{case['id']} {chip}</h2><p>{html.escape(case['note'])}</p>{chips}"
                     f"<table>{''.join(_row(i) for i in case['packet']['items'])}</table></section>")
    parts.append("</body></html>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts))
    print(out)


if __name__ == "__main__":
    render(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT)
