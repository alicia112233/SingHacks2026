"""Draw the book map slide from the exported customer-vector data."""
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = Path(sys.argv[2])
clients = data["clients"]
FOCUS = next(cid for cid, c in clients.items() if c["name"].startswith("Chalermchai"))
LANES = {"exposed": ("#E06A5A", "May be exposed"), "now": ("#D9822B", "Act now"),
         "week": ("#D4B26A", "This week"), "monitor": ("#8FA3C0", "Monitor")}
W, H, PAD = 1000, 600, 60


def pos(c):
    return PAD + (c["map"]["x"] + 1) / 2 * (W - 2 * PAD), PAD + (1 - (c["map"]["y"] + 1) / 2) * (H - 2 * PAD)


def short(name):
    return name.split()[0] if not name.startswith(("Fong", "Lau", "Tan", "Kim", "Zhang", "Chen", "Cheung")) else name.split()[0]


points = {cid: pos(c) for cid, c in clients.items()}
focus = clients[FOCUS]
similar = focus["similar"]
parts = [f'<line x1="{W/2}" y1="20" x2="{W/2}" y2="{H-20}" stroke="#2C3631" stroke-width="2"/>',
         f'<line x1="20" y1="{H/2}" x2="{W-20}" y2="{H/2}" stroke="#2C3631" stroke-width="2"/>']
fx, fy = points[FOCUS]
for item in similar:
    x, y = points[item["client_id"]]
    parts.append(f'<line x1="{fx:.0f}" y1="{fy:.0f}" x2="{x:.0f}" y2="{y:.0f}" stroke="#D4B26A" stroke-width="3" stroke-dasharray="8 7"/>')

placed = []


def free(box):
    return all(box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3] for b in placed)


for cid, (x, y) in points.items():
    placed.append((x - 11, y - 11, x + 11, y + 11))
labels = []
order = [FOCUS] + [s["client_id"] for s in similar] + [cid for cid in clients if cid != FOCUS and cid not in {s["client_id"] for s in similar}]
for cid in order:
    x, y = points[cid]
    name = short(clients[cid]["name"])
    bold = cid == FOCUS or cid in {s["client_id"] for s in similar}
    size = 24 if bold else 20
    w = len(name) * size * 0.55
    for dx, dy, anchor in ((16, 8, "start"), (-16, 8, "end"), (0, -18, "middle"), (0, 32, "middle"), (16, -12, "start"), (16, 26, "start")):
        x0 = x + dx if anchor == "start" else x + dx - w if anchor == "end" else x - w / 2
        box = (x0 - 2, y + dy - size, x0 + w + 2, y + dy + 4)
        if free(box) and 0 <= box[0] and box[2] <= W:
            placed.append(box)
            labels.append(f'<text x="{x + dx:.0f}" y="{y + dy:.0f}" font-size="{size}" font-weight="{600 if bold else 400}" text-anchor="{anchor}" fill="{"#F4EFE6" if bold else "#C9C2B4"}" paint-order="stroke" stroke="#18201C" stroke-width="6">{name}</text>')
            break
for cid, (x, y) in points.items():
    colour = LANES[clients[cid]["lane"]][0]
    if cid == FOCUS:
        parts.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="22" fill="none" stroke="#F4EFE6" stroke-width="3"/>')
    parts.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{13 if cid == FOCUS else 10}" fill="{colour}"/>')
parts += labels
axes = data["axes"]
parts.append(f'<text x="{W/2 + 12:.0f}" y="30" font-size="18" fill="#9C9686" font-family="IBM Plex Mono, monospace">↑ {", ".join(a.lower() for a in axes["y"]["high"])}</text>')
parts.append(f'<text x="{W - 20}" y="{H - 18}" font-size="18" fill="#9C9686" text-anchor="end" font-family="IBM Plex Mono, monospace">{", ".join(a.lower() for a in axes["x"]["high"])} →</text>')
legend = "".join(f'<span style="display:inline-flex;align-items:center;gap:10px"><i style="width:16px;height:16px;border-radius:50%;background:{c}"></i>{label}</span>' for c, label in LANES.values())


def fmt(unit, v):
    if unit == "share":
        return f"{round(v * 100)}%"
    if unit == "points":
        return f"{v * 100:+.0f} pts"
    if unit == "score":
        return f"{v:g}/10"
    if unit == "years":
        return f"{v:g} yrs"
    return f"{v:.1f}x"


rows = "".join(
    f'<div style="display:flex;flex-direction:column;gap:6px;padding:20px 24px;background:#1E2622;border:1px solid #2C3631;border-radius:12px">'
    f'<div style="display:flex;justify-content:space-between;align-items:baseline"><p style="font-size:28px;font-weight:600">{s["name"]}</p><p style="font-size:26px;font-weight:600;color:#D4B26A">{s["similarity"]:.2f}</p></div>'
    f'<p style="font-size:21px;line-height:1.4;color:#B9B2A3">{" · ".join(d["label"] + " " + fmt(d["unit"], d["a"]) + " vs " + fmt(d["unit"], d["b"]) for d in [d for d in s["drivers"] if d["unit"] != "points"][:2])}</p></div>'
    for s in similar[:3])
lane_colour, lane_label = LANES[focus["lane"]]
section = f'''<section id="bookmap" style="background:#18201C;color:#F4EFE6;font-family:'IBM Plex Sans', Arial, sans-serif;padding:100px 128px 120px;display:flex;flex-direction:column;gap:28px">
<div style="display:flex;flex-direction:column;gap:14px">
<p style="font-size:24px;font-weight:600;letter-spacing:4px;text-transform:uppercase;color:#D4B26A">New since SingHacks · customer vectors</p>
<h2 style="font-family:'EB Garamond', Georgia, serif;font-size:68px;font-weight:500;line-height:1.08">Every client is a vector. Lookalike books sit together.</h2>
</div>
<div style="display:flex;gap:48px;align-items:flex-start">
<div style="width:1000px;display:flex;flex-direction:column;gap:14px">
<div style="display:flex;gap:32px;font-size:22px;color:#C9C2B4">{legend}</div>
<svg viewBox="0 0 {W} {H}" style="width:1000px;height:{H}px;background:#1A221E;border:1px solid #2C3631;border-radius:14px" aria-hidden="true" font-family="IBM Plex Sans, Arial, sans-serif">{"".join(parts)}</svg>
</div>
<div style="flex:1;display:flex;flex-direction:column;gap:18px">
<h3 style="font-family:'EB Garamond', Georgia, serif;font-size:48px;font-weight:500;line-height:1.1">{focus["name"]}</h3>
<p style="display:flex;align-items:center;gap:14px;font-size:24px;color:#C9C2B4"><span style="padding:4px 14px;border-radius:999px;background:{lane_colour};color:#18201C;font-weight:600;letter-spacing:2px;text-transform:uppercase;font-size:20px">{lane_label}</span>Urgency {focus["score"]} / 99</p>
<p style="font-size:24px;line-height:1.4;color:#DCD6CA">{focus["tension"]}</p>
<p style="margin-top:6px;font-size:20px;font-weight:600;letter-spacing:3px;text-transform:uppercase;color:#9C9686">Clients like this one</p>
{rows}
</div>
</div>
<p style="position:absolute;left:128px;bottom:52px;width:1664px;font-size:22px;color:#9C9686">24 named numbers per client: exposures, liquidity, obligations, stated profile. Calculated inside the bank, never sent to a model. Similarity, not prediction.</p>
<aside>Siang Woo · 25 seconds. “Our newest feature: customer vectors. Every client becomes 24 named numbers, calculated inside the bank, so books that look alike sit together on this map. Chalermchai’s closest match is Cheung, at 0.85: both are about two-thirds in fixed income with a cautious profile. When an RM handles one, they know which other books to look at, and they can see the reasons, not a black box.”</aside>
</section>
'''
out.write_text(section, encoding="utf-8")
print("ok", focus["name"], [s["name"] for s in similar])
