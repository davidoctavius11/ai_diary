"""
build_gallery.py
----------------
Generates a browsable HTML gallery of analyzed photos + their AI descriptions.
Open data/fusion/gallery.html in any browser — no server needed.

Usage:
    python scripts/build_gallery.py
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
PHOTOS_ANALYZED = BASE_DIR / "data" / "fusion" / "photos_analyzed.json"
GALLERY_OUT = BASE_DIR / "data" / "fusion" / "gallery.html"


def load_photos() -> list[dict]:
    if not PHOTOS_ANALYZED.exists():
        print(f"No analyzed photos yet. Run photo_analyzer.py first.")
        return []
    with open(PHOTOS_ANALYZED, encoding="utf-8") as f:
        return json.load(f)


def photo_rel_path(entry: dict) -> str:
    """Path to photo relative to gallery.html location (both in data/fusion/ vs data/photos/)."""
    filename = entry.get("filename", "")
    return f"../photos/{filename}"


def render_card(entry: dict) -> str:
    img_path = photo_rel_path(entry)
    date = entry.get("date", "unknown date")
    content = entry.get("content", "").replace("<", "&lt;").replace(">", "&gt;")
    # Convert newlines and **bold** markers to HTML
    content_html = content.replace("\n\n", "</p><p>").replace("\n", "<br>")
    content_html = f"<p>{content_html}</p>"
    import re
    content_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content_html)

    return f"""
    <div class="card" data-date="{date}">
      <div class="photo-wrap">
        <img src="{img_path}" alt="{date}" loading="lazy"
             onerror="this.parentElement.innerHTML='<div class=no-img>📷</div>'">
      </div>
      <div class="desc">
        <div class="date">{date}</div>
        <div class="content">{content_html}</div>
      </div>
    </div>"""


def build_html(photos: list[dict]) -> str:
    # Sort newest first
    photos_sorted = sorted(photos, key=lambda p: p.get("date", ""), reverse=True)

    cards = "\n".join(render_card(p) for p in photos_sorted)

    # Collect unique years for filter
    years = sorted({p.get("date", "")[:4] for p in photos if p.get("date", "") and p.get("date", "") != "unknown"}, reverse=True)
    year_options = '<option value="">All years</option>' + "".join(f'<option value="{y}">{y}</option>' for y in years)

    child_name = "Brian / 白小白"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{child_name} 的记忆相册</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #f5f0eb;
    color: #333;
  }}
  header {{
    background: #fff;
    padding: 20px 32px;
    border-bottom: 1px solid #e0d9d0;
    position: sticky; top: 0; z-index: 10;
    display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
  }}
  h1 {{ font-size: 1.4rem; color: #5a3e2b; flex: 1; }}
  .stats {{ font-size: 0.85rem; color: #888; }}
  .controls {{ display: flex; gap: 12px; align-items: center; }}
  input[type=search], select {{
    padding: 7px 12px; border: 1px solid #ddd; border-radius: 8px;
    font-size: 0.9rem; background: #fafafa;
  }}
  input[type=search] {{ width: 220px; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 20px;
    padding: 24px 32px;
    max-width: 1400px;
    margin: 0 auto;
  }}
  .card {{
    background: #fff;
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    display: flex; flex-direction: column;
    transition: transform 0.15s;
  }}
  .card:hover {{ transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.12); }}
  .card.hidden {{ display: none; }}
  .photo-wrap {{
    width: 100%; height: 220px; overflow: hidden;
    background: #eee; flex-shrink: 0;
  }}
  .photo-wrap img {{
    width: 100%; height: 100%; object-fit: cover;
    transition: transform 0.3s;
  }}
  .card:hover .photo-wrap img {{ transform: scale(1.03); }}
  .no-img {{
    width: 100%; height: 100%;
    display: flex; align-items: center; justify-content: center;
    font-size: 3rem; color: #bbb;
  }}
  .desc {{ padding: 16px; flex: 1; }}
  .date {{
    font-size: 0.78rem; font-weight: 600; color: #b07d5a;
    text-transform: uppercase; letter-spacing: 0.05em;
    margin-bottom: 8px;
  }}
  .content {{ font-size: 0.88rem; line-height: 1.6; color: #444; }}
  .content p {{ margin-bottom: 8px; }}
  .content strong {{ color: #5a3e2b; }}
  #no-results {{
    text-align: center; padding: 60px; color: #aaa;
    display: none; grid-column: 1/-1;
  }}
  @media (max-width: 600px) {{
    .grid {{ padding: 12px; gap: 12px; }}
    header {{ padding: 12px 16px; }}
  }}
</style>
</head>
<body>
<header>
  <h1>✨ {child_name}'s Memory Gallery</h1>
  <span class="stats">{len(photos):,} memories</span>
  <div class="controls">
    <input type="search" id="search" placeholder="Search memories…" oninput="filterCards()">
    <select id="yearFilter" onchange="filterCards()">
      {year_options}
    </select>
  </div>
</header>
<div class="grid" id="grid">
  {cards}
  <div id="no-results">No memories found for that search.</div>
</div>
<script>
function filterCards() {{
  const q = document.getElementById('search').value.toLowerCase();
  const year = document.getElementById('yearFilter').value;
  let visible = 0;
  document.querySelectorAll('.card').forEach(card => {{
    const text = card.textContent.toLowerCase();
    const date = card.dataset.date || '';
    const matchQ = !q || text.includes(q);
    const matchY = !year || date.startsWith(year);
    const show = matchQ && matchY;
    card.classList.toggle('hidden', !show);
    if (show) visible++;
  }});
  document.getElementById('no-results').style.display = visible === 0 ? 'block' : 'none';
}}
</script>
</body>
</html>"""


def main():
    photos = load_photos()
    if not photos:
        return

    print(f"Building gallery for {len(photos)} analyzed photos...")
    html = build_html(photos)

    with open(GALLERY_OUT, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Gallery saved to: {GALLERY_OUT}")
    print(f"Opening in browser...")

    import subprocess
    subprocess.run(["open", str(GALLERY_OUT)])


if __name__ == "__main__":
    main()
