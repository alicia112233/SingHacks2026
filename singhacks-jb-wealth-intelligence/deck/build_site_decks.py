"""Build the site's decks from slide files.

slides.html: the full deck in the artifact order, without speaker notes.
pitch.html:  the seven-slide SFF pitch (not linked from the site).

Usage: python deck/build_site_decks.py site site/pitch.html
"""
import json
import re
import sys
from pathlib import Path

here = Path(__file__).parent
deck = here / "deck" / "project" / "slides"

site = Path(sys.argv[1])
template = Path(sys.argv[2]).read_text(encoding="utf-8")

ICONS = {
    "Lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "Search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "Warning": '<path d="M12 3l10 18H2z"/><path d="M12 10v5"/><path d="M12 18h.01"/>',
    "Book": '<path d="M4 5a2 2 0 0 1 2-2h14v16H6a2 2 0 0 0-2 2z"/><path d="M4 21V5"/><path d="M9 7h7"/>',
    "Users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.5a5 5 0 0 1 5.5 5"/>',
}


def icon(match):
    return (f'<svg viewBox="0 0 24 24" style="{match.group(2)};flex:none" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[match.group(1)]}</svg>')


def arrow_shape(match):
    style = match.group(1)
    colour = re.search(r"background:([^;]+)", style).group(1)
    size = re.sub(r"background:[^;]+;?", "", style)
    return (f'<svg viewBox="0 0 96 48" preserveAspectRatio="none" style="{size};flex:none" aria-hidden="true">'
            f'<path d="M0 16H60V2L96 24L60 46V32H0Z" fill="{colour}"/></svg>')


def connectors(html):
    lines = re.findall(r'<x-connector x1="(\d+)" y1="(\d+)" x2="(\d+)" y2="(\d+)"[^>]*></x-connector>\n?', html)
    if not lines:
        return html
    svg = ('<svg style="position:absolute;left:0;top:0;width:1664px;height:540px;overflow:visible" aria-hidden="true">'
           '<defs><marker id="hw-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="16" markerHeight="16" markerUnits="userSpaceOnUse" orient="auto"><path d="M0 0L10 5L0 10z" fill="#18201C"/></marker></defs>'
           + "".join(f'<line x1="{a}" y1="{b}" x2="{c}" y2="{d}" stroke="#18201C" stroke-width="3" marker-end="url(#hw-a)"/>' for a, b, c, d in lines)
           + "</svg>\n")
    html = re.sub(r'<x-connector[^>]*></x-connector>\n?', "", html)
    return html.replace("\n</div>\n<p style=\"position:absolute;left:128px;top:840px", "\n" + svg + "</div>\n<p style=\"position:absolute;left:128px;top:840px", 1)


def render(path, fixes):
    html = path.read_text(encoding="utf-8").strip()
    html = re.sub(r'(<section id="[^"]+") hidden', r"\1", html)
    for a, b in fixes:
        assert a in html, (path.name, a)
        html = html.replace(a, b)
    html = re.sub(r'href="https://claude\.ai/artifact/[^"#]+#(\w+)"', r'href="map.html#\1"', html)
    html = re.sub(r'<x-icon name="(\w+)" style="([^"]*)"></x-icon>', icon, html)
    html = re.sub(r'<x-shape kind="arrow-right" style="([^"]*)"></x-shape>', arrow_shape, html)
    html = connectors(html)
    html = re.sub(r' data-build-in="[^"]*"', "", html)
    assert "<x-" not in html and "claude.ai" not in html, path.name
    return html


TABLES = (".stage table { border-collapse: collapse }\n"
          ".stage th, .stage td { padding: 14px 24px 14px 0; border-bottom: 1px solid rgba(128,128,128,.3); vertical-align: top }\n"
          ".stage th { font-weight: 600; border-bottom: 2px solid currentColor }\n")


def build(slides, out, title, description, notes=True):
    start = template.index('<div class="stage" id="stage">') + len('<div class="stage" id="stage">')
    end = template.index("</div></div>\n<div class=\"notes\"")
    page = template[:start] + "\n" + "\n".join(slides) + "\n" + template[end:]
    page = re.sub(r'<span class="count" id="count" aria-live="polite">1 / \d+</span>', f'<span class="count" id="count" aria-live="polite">1 / {len(slides)}</span>', page)
    page = re.sub(r"<title>[^<]*</title>", f"<title>{title}</title>", page)
    page = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{description}">', page)
    if ".stage table" not in page:
        page = page.replace(".stage aside { display: none }", TABLES + ".stage aside { display: none }", 1)
    if not notes:
        # The public deck carries no speaker notes: strip them and the controls that show them.
        page = re.sub(r"\n?<aside>.*?</aside>", "", page, flags=re.S)
        page = re.sub(r'\s*<button type="button" id="notes-btn"[^>]*>.*?</button>', "", page, flags=re.S)
        page = page.replace("document.getElementById('notes-btn').addEventListener('click', toggleNotes);", "")
        page = page.replace("else if (e.key === 'n' || e.key === 'N') toggleNotes();", "")
        page = page.replace("document.getElementById('notes-btn').setAttribute('aria-pressed', String(on));", "")
    out.write_text(page, encoding="utf-8")
    print("wrote", out.name, len(slides), "slides")


CENTRE_TRUST = ('<div style="display:grid;grid-template-columns:repeat(2, 1fr);gap:32px">',
                '<div style="display:grid;grid-template-columns:repeat(2, 1fr);gap:32px;margin:auto 0">')

pitch = [
    render(deck / "cover.html", []),
    render(deck / "how-it-works.html", [
        (">What just happened<", ">How it works<"),
        ("“Here’s what just happened.", "“Here’s how it works."),
        (", click on each step.", "."),
        (" (click)", ""),
    ]),
    render(deck / "shifts-a.html", []),
    render(deck / "shifts-b.html", []),
    render(deck / "bookmap.html", []),
    render(deck / "trust.html", [CENTRE_TRUST]),
    render(deck / "integration.html", []),
]
build(pitch, site / "pitch.html", "Pitch · TESSERA", "TESSERA by SAPTrio: the seven-slide pitch for the Singapore FinTech Festival finals.")

order = json.loads((deck.parent / "deck.json").read_text(encoding="utf-8"))["order"]
full = [render(deck / f"{sid}.html", [CENTRE_TRUST] if sid == "trust" else []) for sid in order]
build(full, site / "slides.html", "Slides · TESSERA", "TESSERA by SAPTrio: the full deck, from the problem to how it scales in Julius Bär.", notes=False)
