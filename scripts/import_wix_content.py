#!/usr/bin/env python3
"""Fetch Wix blog posts and static pages; emit local wiki HTML (no browsing required)."""

from __future__ import annotations

import csv
import html
import io
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parents[1]
WIKI = REPO / "wiki"
POSTS = WIKI / "posts"
BASE = "https://jayhawksolarteam.wixsite.com"

# Footer on generated pages (team disbanded ~2022; this wiki is a historical archive).
SOURCE_NOTE_HTML = """      <p class="muted source-note">Historical archive of the KU Solar Car student team (University of Kansas; disbanded around 2022).</p>"""
SOURCE_NOTE_CONTACT_HTML = """      <p class="muted source-note">Contact details as published when the team was active (historical record; may be outdated).</p>"""

# Bundled offline copy (see wiki/assets/). Wix page only shows page images of the package.
SPONSORS_PACKAGE_PDF = "assets/KU-Solar-Car-2019-2022-Sponsorship-Partners-Package.pdf"
SPONSORS_PACKAGE_HTML = f"""      <section class="sponsor-pdf" aria-labelledby="sponsor-pdf-h">
        <h2 id="sponsor-pdf-h">2019–2022 Sponsorship / Partners package (full PDF)</h2>
        <p class="muted">Complete document (~6 MB), stored in this wiki for offline use.</p>
        <p><a href="{SPONSORS_PACKAGE_PDF}">Download PDF</a></p>
        <iframe class="pdf-frame" title="KU Solar Car 2019–2022 Sponsorship and Partners package" src="{SPONSORS_PACKAGE_PDF}"></iframe>
      </section>
"""

# Adopt-a-Cell: donor grid was JS-driven on the source site. wiki/partials/adopt_a_cell_widget.html + assets + CSV → interactive mirror; else placeholder.
ADOPT_A_CELL_WIDGET_PARTIAL = WIKI / "partials" / "adopt_a_cell_widget.html"
ADOPT_A_CELL_DONORS_CSV = WIKI / "partials" / "adopt_a_cell_donors.csv"
ADOPT_A_CELL_SVG_ASSET = WIKI / "assets" / "adopt-a-cell-grid.svg"
ADOPT_A_CELL_WIDGET_HTML = """      <section class="adopt-widget" aria-labelledby="adopt-widget-h">
        <h2 id="adopt-widget-h">Cell grid &amp; progress (offline stand-in)</h2>
        <p class="muted">The campaign used an interactive grid of sponsored cells. This section is a simplified stand-in when the full widget is not bundled.</p>
        <p class="adopt-label">Archival display only (not live donation data):</p>
        <div class="adopt-progress" role="img" aria-label="Representative full progress bar for display">
          <div class="adopt-progress-fill"></div>
        </div>
        <p class="muted">To support the team today: <a href="sponsors.html">Partners &amp; sponsorship</a> · <a href="contact.html">Contact</a></p>
      </section>
"""
# Same partner logos as wiki/sponsors.html (Platinum + Gold); refresh if sponsors import changes.
ADOPT_PARTNER_LOGO_ROWS: tuple[tuple[str, str], ...] = (
    (
        "https://static.wixstatic.com/media/effc6b_72d835aec9264ff3a2987e5f77e7de23~mv2.jpg/v1/crop/x_0,y_52,w_500,h_396/fill/w_156,h_124,al_c,q_80,usm_0.66_1.00_0.01,enc_avif,quality_auto/peaslee-tech.jpg",
        "Peaslee Tech",
    ),
    (
        "https://static.wixstatic.com/media/225656_ade8666cab8d4764b01b1a9621295057~mv2.png/v1/fill/w_124,h_125,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/10517415_810594148982102_493333484777200.png",
        "Partner",
    ),
    (
        "https://static.wixstatic.com/media/ff2444_c6951efafaa84c3b8b51e0d28385c404~mv2_d_7095_2028_s_2.gif",
        "KU School of Engineering",
    ),
    (
        "https://static.wixstatic.com/media/ff2444_ed0a50a923ea45a88faaf4c87d714d3e~mv2.jpeg/v1/fill/w_131,h_132,al_c,q_80,usm_0.66_1.00_0.01,enc_avif,quality_auto/ESC_Logo.jpeg",
        "ESC",
    ),
    (
        "https://static.wixstatic.com/media/4bcb51_39d2b82995144d9e916dbb604e55e7c9~mv2.png/v1/fill/w_295,h_58,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/4bcb51_39d2b82995144d9e916dbb604e55e7c9~mv2.png",
        "Partner",
    ),
    (
        "https://static.wixstatic.com/media/9521c4_e544b9d547ed413f957839550e5dc36b~mv2.jpg/v1/crop/x_408,y_0,w_5359,h_1684/fill/w_315,h_99,al_c,q_80,usm_0.66_1.00_0.01,enc_avif,quality_auto/9521c4_e544b9d547ed413f957839550e5dc36b~mv2.jpg",
        "Partner",
    ),
    (
        "https://static.wixstatic.com/media/effc6b_dfe9199d9d4640e0a94c701f2ed77ee6~mv2.png/v1/fill/w_247,h_80,al_c,lg_1,q_85,enc_avif,quality_auto/spearps_logo.png",
        "Spear Power Systems",
    ),
    (
        "https://static.wixstatic.com/media/4bcb51_2cd264b4aa3b4cc7b269bd7d20ea3ef6~mv2.png/v1/crop/x_0,y_102,w_1700,h_1598/fill/w_100,h_94,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/4bcb51_2cd264b4aa3b4cc7b269bd7d20ea3ef6~mv2.png",
        "Partner",
    ),
)


def _adopt_a_cell_interactive_html() -> str:
    """Interactive donor grid + CSV when partial, SVG, and donors file exist; else placeholder."""
    if (
        not ADOPT_A_CELL_WIDGET_PARTIAL.exists()
        or not ADOPT_A_CELL_SVG_ASSET.exists()
        or not ADOPT_A_CELL_DONORS_CSV.exists()
    ):
        return ADOPT_A_CELL_WIDGET_HTML
    out = ADOPT_A_CELL_WIDGET_PARTIAL.read_text(encoding="utf-8")
    svg = ADOPT_A_CELL_SVG_ASSET.read_text(encoding="utf-8")
    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg, flags=re.I)
    out = out.replace("__ADOPT_SVG__", svg)
    csv_text = ADOPT_A_CELL_DONORS_CSV.read_text(encoding="utf-8").strip()
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    out = out.replace("__ADOPT_ROWS_JSON__", json.dumps(rows))
    return out


def _adopt_a_cell_partner_logos_html() -> str:
    fig_lines = [
        "      <figure class=\"post-img\"><img src=\""
        + html.escape(url)
        + "\" alt=\""
        + html.escape(alt)
        + "\" loading=\"lazy\" decoding=\"async\"></figure>"
        for url, alt in ADOPT_PARTNER_LOGO_ROWS
    ]
    return f"""      <section class="adopt-partners" aria-labelledby="adopt-partners-h">
        <h2 id="adopt-partners-h">Partners &amp; sponsors</h2>
        <p>Many Adopt-a-Cell donors are the same people and organizations we thank as team partners. We still list them on the <a href="sponsors.html">Partners</a> page; key logos are repeated here.</p>
        <div class="adopt-logo-grid">
{chr(10).join(fig_lines)}
        </div>
      </section>
"""


USER_AGENT = "KU-Solar-Car-wiki-import/1.0 (local static wiki)"

# Any Wix CDN media URL in HTML (src, JSON, background-image, etc.)
WIX_MEDIA_RE = re.compile(
    r"https://static\.wixstatic\.com/media/[a-zA-Z0-9_~.-]+(?:/[^\"'\s<>)]*)?",
    re.I,
)


def _media_key_from_wix_url(url: str) -> str | None:
    m = re.search(r"/media/([^/?#]+)", url)
    if not m:
        return None
    return m.group(1).split("/")[0]


def _url_quality_score(url: str) -> int:
    mw = mh = 0
    for m in re.finditer(r"[/,]w_(\d+),", url):
        mw = max(mw, int(m.group(1)))
    for m in re.finditer(r"h_(\d+),", url):
        mh = max(mh, int(m.group(1)))
    return mw * 100_000 + mh


def _good_enough_url_for_supplement(url: str) -> bool:
    m = re.search(r"/w_(\d+),", url)
    w = int(m.group(1)) if m else 0
    if w and w <= 32:
        return False
    if w and w <= 48 and "blur_2" in url:
        return False
    return True


def _seen_media_keys_from_blocks(blocks: list[tuple]) -> set[str]:
    keys: set[str] = set()
    for b in blocks:
        if b[0] != "img":
            continue
        k = _media_key_from_wix_url(b[1])
        if k:
            keys.add(k)
    return keys


def _html_for_static_regex_scan(root) -> str:
    """Strip chrome, scripts, and styles so regex scan matches main content only."""
    s = BeautifulSoup(str(root), "html.parser")
    main = s.find(id="main_MF") or s.body or s
    for bid in ("SITE_HEADER", "SITE_FOOTER", "WIX_ADS"):
        t = main.find(id=bid)
        if t:
            t.decompose()
    for t in list(
        main.find_all(
            class_=lambda c: c and ("recent-post" in str(c) or "blog-post-list" in str(c))
        )
    ):
        t.decompose()
    for tag in main.find_all("script"):
        tag.decompose()
    for tag in main.find_all("style"):
        tag.decompose()
    return str(main)


def _html_for_blog_regex_scan(root) -> str:
    s = BeautifulSoup(str(root), "html.parser")
    el = s.find("article") or s.body or s
    for tag in el.find_all("script"):
        tag.decompose()
    for tag in el.find_all("style"):
        tag.decompose()
    return str(el)


def _collect_supplemental_wix_images(html: str, seen_keys: set[str]) -> list[tuple]:
    """URLs present in HTML but not covered by DOM extraction (by Wix media file id)."""
    entries: list[tuple[int, str, str, int]] = []
    for m in WIX_MEDIA_RE.finditer(html):
        url = m.group(0).rstrip(".,;)")
        if not _good_enough_url_for_supplement(url):
            continue
        key = _media_key_from_wix_url(url)
        if not key or key in seen_keys:
            continue
        entries.append((m.start(), key, url, _url_quality_score(url)))

    by_key: dict[str, list[tuple[int, str, int]]] = {}
    for pos, key, url, q in entries:
        by_key.setdefault(key, []).append((pos, url, q))

    ordered: list[tuple[int, str]] = []
    for key, lst in by_key.items():
        best = max(lst, key=lambda x: x[2])
        best_url = best[1]
        if not _good_enough_url_for_supplement(best_url):
            continue
        first_pos = min(x[0] for x in lst)
        ordered.append((first_pos, best_url))

    ordered.sort(key=lambda x: x[0])
    return [("img", u, "") for _, u in ordered]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def meta_title(soup: BeautifulSoup) -> str:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return html.unescape(og["content"].strip())
    t = soup.find("title")
    return html.unescape(t.get_text(strip=True)) if t else "Untitled"


def wiki_title_from_soup(soup: BeautifulSoup, fallback: str) -> str:
    """Strip ``| KU Solar Car`` suffix from og/title for page H1."""
    t = meta_title(soup)
    if not t:
        return fallback
    t = re.sub(r"\s*\|\s*KU Solar Car\s*$", "", t, flags=re.I).strip()
    return t or fallback


def meta_date(soup: BeautifulSoup) -> str | None:
    for prop in ("article:published_time", "og:updated_time"):
        m = soup.find("meta", property=prop)
        if m and m.get("content"):
            return m["content"][:10]
    j = soup.find("script", type="application/ld+json")
    if j and j.string:
        try:
            data = json.loads(j.string)
            if isinstance(data, dict) and "datePublished" in data:
                return str(data["datePublished"])[:10]
        except Exception:
            pass
    return None


def _blog_post_root(soup: BeautifulSoup):
    """Main post article only (excludes recent-posts sidebar inside TPAMultiSection)."""
    art = soup.find("article", class_=lambda c: c and "tgMH9T" in c)
    if art:
        return art
    return soup.select_one('div[id^="TPAMultiSection_"]') or soup.find("body")


def _best_wix_img_url(img) -> str:
    """Prefer data-pin-media, then largest srcset entry, then src."""
    if img.get("data-pin-media"):
        return img["data-pin-media"].strip()
    ss = img.get("srcset") or ""
    if ss:
        best_url, best_w = "", 0
        for chunk in ss.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            parts = chunk.split()
            u = parts[0]
            m = re.search(r"/w_(\d+),", u)
            w = int(m.group(1)) if m else 0
            if w > best_w:
                best_w, best_url = w, u
        if best_url:
            return best_url
    return (img.get("src") or "").strip()


def _url_from_wow_image(el) -> str | None:
    """Full image URL from Wix ``<wow-image data-image-info='...'>`` (avoids tiny nested img)."""
    raw = el.get("data-image-info")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    idata = data.get("imageData") or {}
    uri = idata.get("uri")
    if not uri:
        return None
    w = int(idata.get("width") or 1200)
    h = int(idata.get("height") or 800)
    w = max(w, 1)
    h = max(h, 1)
    w_disp = min(w, 2000)
    h_disp = max(1, int(h * (w_disp / w)))
    fname = uri.split("/")[-1]
    base = f"https://static.wixstatic.com/media/{uri}"
    return f"{base}/v1/fit/w_{w_disp},h_{h_disp},al_c,q_90/{fname}"


def extract_blog_ordered(soup: BeautifulSoup) -> list[tuple]:
    """Paragraphs, headings, and inline images in document order.

    Scoped to the main post ``article`` so sidebar thumbnails are not included.
    """
    root = _blog_post_root(soup)
    if not root:
        return []
    blocks: list[tuple] = []
    seen_img: set[str] = set()
    for el in root.find_all(
        ["p", "h1", "h2", "h3", "h4", "h5", "h6", "figure", "wow-image"], recursive=True
    ):
        if el.name != "figure" and el.find_parent("figure"):
            continue
        if el.name == "wow-image":
            if el.find_parent("figure"):
                continue
            src = _url_from_wow_image(el)
            if not src or src in seen_img:
                continue
            seen_img.add(src)
            name = ""
            try:
                raw = el.get("data-image-info") or "{}"
                name = (json.loads(raw).get("imageData") or {}).get("name") or ""
            except json.JSONDecodeError:
                pass
            blocks.append(("img", src, name))
            continue
        if el.name == "figure":
            if el.get("data-hook") != "figure-IMAGE":
                continue
            img = el.find("img")
            if not img:
                continue
            src = _best_wix_img_url(img)
            if not src or "static.wixstatic.com" not in src:
                continue
            if src in seen_img:
                continue
            seen_img.add(src)
            alt = (img.get("alt") or "").strip()
            blocks.append(("img", src, alt))
            continue
        classes = " ".join(el.get("class") or [])
        if "dzhEF" not in classes and not (
            "fpTX4" in classes and el.name.startswith("h")
        ):
            continue
        if el.find_parent("figure"):
            continue
        text = el.get_text(" ", strip=True)
        if text:
            blocks.append(("text", el.name, text))
    scan_html = _html_for_blog_regex_scan(root)
    seen_keys = _seen_media_keys_from_blocks(blocks)
    blocks.extend(_collect_supplemental_wix_images(scan_html, seen_keys))
    return blocks


NAV_LINES = {
    "home",
    "news",
    "races",
    "team",
    "our legacy",
    "astra",
    "subteams",
    "faculty",
    "partners",
    "adopt-a-cell",
    "benefits",
    "current",
    "sponsor us",
    "contact us",
    "privacy & terms",
}


def _static_main_root(soup: BeautifulSoup):
    """Main page column (excludes outer chrome wrappers)."""
    return soup.find(id="main_MF") or soup.find(id="SITE_CONTAINER") or soup.find("body")


def _in_site_chrome(el) -> bool:
    """True if node is inside Wix header, footer, or top ad strip."""
    a = el
    while a is not None:
        aid = str(a.get("id") or "")
        if aid in ("SITE_HEADER", "SITE_FOOTER", "WIX_ADS"):
            return True
        a = a.parent
    return False


def _in_blog_sidebar(el) -> bool:
    """Recent posts / blog list widgets (not page content)."""
    a = el
    while a is not None:
        cls = " ".join(a.get("class") or [])
        if "recent-post" in cls or "blog-post-list" in cls:
            return True
        a = a.parent
    return False


def _in_static_excluded_zone(el) -> bool:
    return _in_site_chrome(el) or _in_blog_sidebar(el)


def _should_skip_static_text(t: str, *, is_heading: bool = False) -> bool:
    """Filter nav / boilerplate from rich text on static pages."""
    footer_addr = "University of Kansas, School of Engineering"
    skip_substrings = (
        "Thanks! Message sent.",
        "This website was built on Wix",
    )
    if not t:
        return True
    if any(s in t for s in skip_substrings):
        return True
    if footer_addr in t and len(t) < 120:
        return True
    low = t.lower()
    if low in NAV_LINES:
        return True
    if t in ("Team | KU Solar Car", "Contact | KU Solar Car", "Races | KU Solar Car"):
        return True
    if "Home News Races" in t and len(t) < 100:
        return True
    if "Team Our Legacy Astra" in t and "Subteams" in t:
        return True
    if "Partners Adopt-A-Cell" in t and "Sponsor Us" in t:
        return True
    if not is_heading and len(t) < 12:
        return True
    if len(t) < 90:
        tokens = [x.strip().lower() for x in t.replace("|", " ").split() if x.strip()]
        if tokens and all(x in NAV_LINES or len(x) < 2 for x in tokens[:8]):
            return True
    return False


def _is_static_content_image(img) -> bool:
    """Non-chrome content images (sponsor logos, photos, etc.)."""
    src = _best_wix_img_url(img)
    if not src or "static.wixstatic.com" not in src:
        return False
    if _in_static_excluded_zone(img):
        return False
    m = re.search(r"/w_(\d+),", src)
    w = int(m.group(1)) if m else 0
    if w and w <= 32:
        return False
    if w and w <= 48 and "blur_2" in src:
        return False
    return True


STATIC_RICH_BLOCK_TAGS = frozenset(
    {"h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol"}
)


def _is_top_level_static_block(container, tag) -> bool:
    """True if ``tag`` is a block element not nested under another block in ``container``."""
    if not getattr(tag, "name", None) or tag.name not in STATIC_RICH_BLOCK_TAGS:
        return False
    anc = tag.parent
    while anc is not None and anc is not container:
        if getattr(anc, "name", None) in STATIC_RICH_BLOCK_TAGS:
            return False
        anc = anc.parent
    return True


def _static_rich_text_pieces(rt_el) -> list[tuple]:
    """Headings, paragraphs, and lists from one Wix ``richTextElement`` (preserve structure)."""
    out: list[tuple] = []
    for tag in rt_el.find_all(list(STATIC_RICH_BLOCK_TAGS), recursive=True):
        if not _is_top_level_static_block(rt_el, tag):
            continue
        if tag.name == "ul":
            lis = tag.find_all("li", recursive=False)
            inner = "".join(
                f"<li>{html.escape(li.get_text(' ', strip=True))}</li>" for li in lis
            )
            if inner:
                out.append(("html", f"<ul>{inner}</ul>"))
            continue
        if tag.name == "ol":
            lis = tag.find_all("li", recursive=False)
            inner = "".join(
                f"<li>{html.escape(li.get_text(' ', strip=True))}</li>" for li in lis
            )
            if inner:
                out.append(("html", f"<ol>{inner}</ol>"))
            continue
        t = tag.get_text(" ", strip=True)
        if not t:
            continue
        if _should_skip_static_text(t, is_heading=tag.name.startswith("h")):
            continue
        out.append(("text", tag.name, t))
    if not out:
        t = rt_el.get_text(" ", strip=True)
        if t and not _should_skip_static_text(t, is_heading=False):
            out.append(("text", "p", t))
    return out


def _strip_leading_duplicate_h1(blocks: list[tuple], title: str) -> list[tuple]:
    """Avoid ``<h1>`` twice when Wix repeats the page title in the first rich block."""
    if not blocks or title.strip() == "":
        return blocks
    b0 = blocks[0]
    if b0[0] != "text" or b0[1] != "h1":
        return blocks
    if b0[2].strip().lower() == title.strip().lower():
        return blocks[1:]
    return blocks


def _first_hero_image_block(blocks: list[tuple]) -> tuple | None:
    """First image that is not a tiny LQIP placeholder."""
    for b in blocks:
        if b[0] != "img":
            continue
        src = b[1]
        m = re.search(r"/w_(\d+),", src)
        w = int(m.group(1)) if m else 0
        if "blur_2" in src and w and w < 250:
            continue
        return b
    for b in blocks:
        if b[0] == "img":
            return b
    return None


def extract_static_ordered(soup: BeautifulSoup) -> list[tuple]:
    """Rich text and images in document order (static Wix pages, not blog posts).

    Includes ``wow-image`` components (full ``data-image-info`` URL) and best ``src``/srcset for ``img``.
    """
    root = _static_main_root(soup)
    if not root:
        return []
    blocks: list[tuple] = []
    seen_img_src: set[str] = set()
    for el in root.find_all(["div", "figure", "wow-image", "img"], recursive=True):
        if el.name == "div" and el.get("data-testid") == "richTextElement":
            for piece in _static_rich_text_pieces(el):
                blocks.append(piece)
        elif el.name == "wow-image":
            if _in_static_excluded_zone(el):
                continue
            src = _url_from_wow_image(el)
            if not src or src in seen_img_src:
                continue
            seen_img_src.add(src)
            name = ""
            try:
                raw = el.get("data-image-info") or "{}"
                name = (json.loads(raw).get("imageData") or {}).get("name") or ""
            except json.JSONDecodeError:
                pass
            blocks.append(("img", src, name))
        elif el.name == "figure":
            if el.get("data-hook") != "figure-IMAGE":
                continue
            if _in_static_excluded_zone(el):
                continue
            img = el.find("img")
            if not img:
                continue
            src = _best_wix_img_url(img)
            if not src or "static.wixstatic.com" not in src:
                continue
            if src in seen_img_src:
                continue
            seen_img_src.add(src)
            alt = (img.get("alt") or "").strip()
            blocks.append(("img", src, alt))
        elif el.name == "img":
            if el.find_parent("figure") or el.find_parent("wow-image"):
                continue
            if not _is_static_content_image(el):
                continue
            src = _best_wix_img_url(el)
            if src in seen_img_src:
                continue
            seen_img_src.add(src)
            alt = (el.get("alt") or "").strip()
            blocks.append(("img", src, alt))
    scan_html = _html_for_static_regex_scan(root)
    seen_keys = _seen_media_keys_from_blocks(blocks)
    blocks.extend(_collect_supplemental_wix_images(scan_html, seen_keys))
    return blocks


def blocks_to_html(blocks: list[tuple]) -> str:
    out: list[str] = []
    for b in blocks:
        if b[0] == "img":
            _, src, alt = b
            out.append(
                f'<figure class="post-img"><img src="{html.escape(src)}" '
                f'alt="{html.escape(alt)}" loading="lazy" decoding="async"></figure>'
            )
        elif b[0] == "html":
            out.append(b[1])
        else:
            _, tag, text = b
            esc = html.escape(text)
            if tag == "p":
                out.append(f"<p>{esc}</p>")
            else:
                out.append(f"<{tag}>{esc}</{tag}>")
    return "\n".join(out)


def page_shell(
    title: str,
    inner: str,
    relpath_to_wiki: str = "..",
    *,
    back_href: str = "news.html",
    back_label: str = "News archive",
) -> str:
    nav = f"""      <nav class="wiki-nav" aria-label="Wiki">
        <a href="{relpath_to_wiki}/index.html">Home</a>
        <a href="{relpath_to_wiki}/mission.html">Mission</a>
        <a href="{relpath_to_wiki}/cars.html">Astra</a>
        <a href="{relpath_to_wiki}/races.html">Races</a>
        <a href="{relpath_to_wiki}/team.html">Team</a>
        <a href="{relpath_to_wiki}/legacy.html">Legacy</a>
        <a href="{relpath_to_wiki}/join.html">Join</a>
        <a href="{relpath_to_wiki}/sponsors.html">Sponsors</a>
        <a href="{relpath_to_wiki}/adopt-a-cell.html">Adopt a Cell</a>
        <a href="{relpath_to_wiki}/news.html">News</a>
        <a href="{relpath_to_wiki}/contact.html">Contact</a>
        <a href="{relpath_to_wiki}/privacy-terms.html">Privacy</a>
      </nav>"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} · KU Solar Car Wiki</title>
  <link rel="stylesheet" href="{relpath_to_wiki}/wiki.css">
</head>
<body>
  <header class="site-header">
    <div class="inner">
      <div class="site-title"><a href="{relpath_to_wiki}/index.html">KU Solar Car Wiki</a></div>
{nav}
    </div>
  </header>
  <div class="wrap">
    <main class="article-body">
{inner}
    </main>
    <footer class="site-footer">
      <a href="{relpath_to_wiki}/{back_href}">← {html.escape(back_label)}</a>
    </footer>
  </div>
</body>
</html>
"""


def import_blog_posts() -> list[tuple[str, str, str]]:
    """Returns list of (slug, title, date) for posts written."""
    xml = fetch(f"{BASE}/kusc/blog-posts-sitemap.xml")
    root = ET.fromstring(xml)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [loc.text for loc in root.findall(".//sm:loc", ns)]
    written: list[tuple[str, str, str]] = []
    POSTS.mkdir(parents=True, exist_ok=True)

    for url in urls:
        if "/post/" not in url:
            continue
        slug = url.rstrip("/").split("/post/")[-1]
        try:
            raw = fetch(url)
        except Exception as e:
            print(f"SKIP {slug}: {e}", file=sys.stderr)
            continue
        soup = BeautifulSoup(raw, "html.parser")
        title = meta_title(soup)
        date = meta_date(soup)
        blocks = extract_blog_ordered(soup)
        if not blocks:
            print(f"SKIP {slug}: no blog blocks", file=sys.stderr)
            continue
        date_line = f'<p class="muted">Published: {html.escape(date)}</p>' if date else ""
        inner = f"""      <h1>{html.escape(title)}</h1>
{date_line}
{blocks_to_html(blocks)}
{SOURCE_NOTE_HTML}"""
        path = POSTS / f"{slug}.html"
        path.write_text(
            page_shell(title, inner, relpath_to_wiki="..", back_href="news.html", back_label="News archive"),
            encoding="utf-8",
        )
        written.append((slug, title, date or ""))
        print(f"OK {slug}")

    return written


def import_static_page(path_slug: str, out_name: str, page_title: str) -> None:
    url = f"{BASE}/kusc/{path_slug}"
    try:
        raw = fetch(url)
    except Exception as e:
        print(f"SKIP static {path_slug}: {e}", file=sys.stderr)
        return
    soup = BeautifulSoup(raw, "html.parser")
    if path_slug == "contact":
        inner = f"""      <h1>{html.escape(page_title)}</h1>
      <p>Text or call: (785) 691-5210</p>
      <p>Email: <a href="mailto:solarcar@ku.edu">solarcar@ku.edu</a></p>
      <p>University of Kansas, School of Engineering, West 15th Street, Lawrence, KS, USA</p>
{SOURCE_NOTE_CONTACT_HTML}"""
        out = WIKI / out_name
        out.write_text(
            page_shell(
                page_title,
                inner,
                relpath_to_wiki=".",
                back_href="index.html",
                back_label="Wiki home",
            ),
            encoding="utf-8",
        )
        print(f"OK static {out_name}")
        return
    blocks = extract_static_ordered(soup)
    if not blocks:
        print(f"SKIP static {path_slug}: no content", file=sys.stderr)
        return
    display_title = wiki_title_from_soup(soup, page_title)
    blocks = _strip_leading_duplicate_h1(blocks, display_title)
    extra = ""
    if path_slug == "cars":
        extra = """      <p class="muted">Longer <a href="astra.html">design article</a> (curated wiki page).</p>
"""
    body_html = blocks_to_html(blocks)
    if path_slug == "sponsors":
        # Full PDF first; Wix body is mostly page images of the same document.
        inner = f"""      <h1>{html.escape(display_title)}</h1>
{extra}{SPONSORS_PACKAGE_HTML}{body_html}
{SOURCE_NOTE_HTML}"""
    elif path_slug == "adopt-a-cell":
        # Order: interactive grid (SVG + CSV) → Wix copy (“cells above”) → partner logos.
        inner = f"""      <h1>{html.escape(display_title)}</h1>
{extra}{_adopt_a_cell_interactive_html()}{body_html}
{_adopt_a_cell_partner_logos_html()}
{SOURCE_NOTE_HTML}"""
    else:
        inner = f"""      <h1>{html.escape(display_title)}</h1>
{extra}{body_html}
{SOURCE_NOTE_HTML}"""
    out = WIKI / out_name
    out.write_text(
        page_shell(
            display_title,
            inner,
            relpath_to_wiki=".",
            back_href="index.html",
            back_label="Wiki home",
        ),
        encoding="utf-8",
    )
    print(f"OK static {out_name}")


def write_news_index(posts: list[tuple[str, str, str]]) -> None:
    """Local news.html listing (newest first)."""
    nav = """      <nav class="wiki-nav" aria-label="Wiki">
        <a href="index.html">Home</a>
        <a href="mission.html">Mission</a>
        <a href="cars.html">Astra</a>
        <a href="races.html">Races</a>
        <a href="team.html">Team</a>
        <a href="legacy.html">Legacy</a>
        <a href="join.html">Join</a>
        <a href="sponsors.html">Sponsors</a>
        <a href="adopt-a-cell.html">Adopt a Cell</a>
        <a href="news.html">News</a>
        <a href="contact.html">Contact</a>
        <a href="privacy-terms.html">Privacy</a>
      </nav>"""
    sorted_posts = sorted(posts, key=lambda x: x[2], reverse=True)
    items: list[str] = []
    for slug, title, date in sorted_posts:
        href = f"posts/{slug}.html"
        items.append(
            f"        <li>\n"
            f'          <a href="{html.escape(href)}">{html.escape(title)}</a>\n'
            f'          <div class="meta">{html.escape(date)}</div>\n'
            f"        </li>"
        )
    items_html = "\n".join(items)
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>News archive · KU Solar Car Wiki</title>
  <link rel="stylesheet" href="wiki.css">
</head>
<body>
  <header class="site-header">
    <div class="inner">
      <div class="site-title"><a href="index.html">KU Solar Car Wiki</a></div>
{nav}
    </div>
  </header>
  <div class="wrap">
    <main>
      <h1>News archive</h1>
      <p class="muted">Historical archive: full blog posts ({len(sorted_posts)} posts), newest first. Dates are original publication dates.</p>
      <ul class="news-list">
{items_html}
      </ul>
    </main>
    <footer class="site-footer">
      <a href="index.html">← Wiki home</a>
    </footer>
  </div>
</body>
</html>
"""
    (WIKI / "news.html").write_text(body, encoding="utf-8")
    print("OK news.html")


def main() -> None:
    WIKI.mkdir(parents=True, exist_ok=True)
    posts = import_blog_posts()
    # Static pages (full mirror; paths from pages-sitemap).
    # astra.html is curated in-repo (merged layout / links).
    static = [
        ("cars", "cars.html", "Astra"),
        ("races", "races.html", "Races"),
        ("team", "team.html", "Team"),
        ("sponsors", "sponsors.html", "Partners & sponsorship"),
        ("legacy", "legacy.html", "Legacy"),
        ("join-us", "join.html", "Join us"),
        ("adopt-a-cell", "adopt-a-cell.html", "Adopt a Cell"),
        ("contact", "contact.html", "Contact"),
        ("privacy-terms", "privacy-terms.html", "Privacy & Terms"),
        ("subscribe", "subscribe.html", "Subscribe"),
        ("interest-page", "interest-page.html", "Interest"),
    ]
    for slug, fname, title in static:
        import_static_page(slug, fname, title)

    # Homepage mission + partner blurb (+ first hero image from home)
    try:
        home_raw = fetch(f"{BASE}/kusc")
        hsoup = BeautifulSoup(home_raw, "html.parser")
        home_blocks = extract_static_ordered(hsoup)
        first_img = _first_hero_image_block(home_blocks)
        text_parts: list[str] = []
        for b in home_blocks:
            if b[0] == "img":
                continue
            _, _tag, t = b
            if "build solar-powered vehicles to compete" in t or "We build solar-powered" in t:
                text_parts.append(f"<blockquote><p>{html.escape(t)}</p></blockquote>")
            elif "raising funds" in t.lower() or "Formula Sun Grand Prix" in t:
                text_parts.append(f"<p>{html.escape(t)}</p>")
        inner_parts: list[str] = []
        if first_img:
            inner_parts.append(blocks_to_html([first_img]).strip())
        inner_parts.extend(text_parts)
        if inner_parts:
            inner = f"""      <h1>Mission</h1>
{chr(10).join(inner_parts)}
{SOURCE_NOTE_HTML}"""
            (WIKI / "mission.html").write_text(
                page_shell(
                    "Mission",
                    inner,
                    relpath_to_wiki=".",
                    back_href="index.html",
                    back_label="Wiki home",
                ),
                encoding="utf-8",
            )
            print("OK mission.html")
    except Exception as e:
        print(f"mission home extract: {e}", file=sys.stderr)

    write_news_index(posts)
    lines = [f"{slug}\t{title}\t{date}" for slug, title, date in posts]
    (REPO / "scripts" / "_imported_posts.tsv").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(posts)} posts, manifest scripts/_imported_posts.tsv")


if __name__ == "__main__":
    main()
