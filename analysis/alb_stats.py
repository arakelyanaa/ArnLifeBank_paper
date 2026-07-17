#!/usr/bin/env python3
"""
ArmLifeBank SEEK access & download statistics
Fetches view and download counts from HTML pages (counts are not in the JSON API).
Writes output/alb_stats.md.
"""

import json
import re
import statistics
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL   = "https://armlifebank.am"
ASSET_TYPES = ["data_files", "models", "sops", "documents", "presentations", "publications"]
CACHE_DIR  = Path(__file__).parent / "cache"
OUTPUT_DIR = Path(__file__).parent / "output"
DELAY      = 0.5   # seconds between requests
SNAPSHOT   = date.today().isoformat()

CACHE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

session = requests.Session()
session.headers.update({"User-Agent": "ArmLifeBank-stats/1.0 (research; arakelyanaa@gmail.com)"})

# ── Helpers ────────────────────────────────────────────────────────────────────

def fetch_with_cache(url: str, cache_key: str, *, as_json: bool = False):
    """Fetch URL, using disk cache. Returns text (or parsed JSON if as_json)."""
    cache_file = CACHE_DIR / f"{cache_key}.{'json' if as_json else 'html'}"
    if cache_file.exists():
        raw = cache_file.read_text(encoding="utf-8")
        return json.loads(raw) if as_json else raw

    for attempt in range(3):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            cache_file.write_text(r.text, encoding="utf-8")
            time.sleep(DELAY)
            return json.loads(r.text) if as_json else r.text
        except requests.RequestException as exc:
            print(f"  Attempt {attempt+1} failed for {url}: {exc}")
            if attempt < 2:
                time.sleep(2 ** attempt * 2)
            else:
                raise


def get_item_ids(asset_type: str) -> list[int]:
    """Return all item IDs for an asset type via the JSON list endpoint."""
    url = f"{BASE_URL}/{asset_type}.json?page=1&per_page=1000"
    data = fetch_with_cache(url, f"list_{asset_type}", as_json=True)
    return [int(item["id"]) for item in data.get("data", [])]


def get_counts_from_html(asset_type: str, item_id: int) -> dict | None:
    """
    Fetch the HTML page for an item and extract view + download counts.
    Returns {"views": int, "downloads": int} or None if not parseable.
    """
    url = f"{BASE_URL}/{asset_type}/{item_id}"
    cache_key = f"html_{asset_type}_{item_id}"
    html = fetch_with_cache(url, cache_key)

    soup = BeautifulSoup(html, "html.parser")

    # SEEK stores counts in: <p id="usage_count">
    usage_p = soup.find("p", id="usage_count")
    if usage_p is None:
        # Fallback: search the full text for the pattern
        text = soup.get_text(" ")
        m_views = re.search(r"Views:\s*(\d+)", text)
        m_dls   = re.search(r"Downloads:\s*(\d+)", text)
        if m_views:
            return {"views": int(m_views.group(1)), "downloads": int(m_dls.group(1)) if m_dls else 0}
        print(f"  WARNING: no usage_count element found for {asset_type}/{item_id}")
        return None

    text = usage_p.get_text(" ")
    m_views = re.search(r"Views:\s*(\d+)", text)
    m_dls   = re.search(r"Downloads:\s*(\d+)", text)
    if not m_views:
        print(f"  WARNING: could not parse view count for {asset_type}/{item_id}: {text!r}")
        return None
    # Downloads may be absent (e.g. publications have no downloadable file) → treat as 0
    return {"views": int(m_views.group(1)), "downloads": int(m_dls.group(1)) if m_dls else 0}


def compute_stats(values: list[int]) -> dict:
    """Mean, sample SD (ddof=1), max — matching LHA definitions."""
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "max": None}
    mean = sum(values) / n
    sd   = statistics.stdev(values) if n > 1 else 0.0
    return {"n": n, "mean": f"{mean:.2f}", "sd": f"{sd:.2f}", "max": max(values)}


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    all_views     = []
    all_downloads = []
    type_summary  = []
    errors        = []

    for asset_type in ASSET_TYPES:
        print(f"\n=== {asset_type} ===")
        try:
            ids = get_item_ids(asset_type)
        except Exception as exc:
            print(f"  Could not list {asset_type}: {exc}")
            errors.append(f"{asset_type}: listing failed — {exc}")
            continue

        if not ids:
            print("  0 items, skipping.")
            type_summary.append({"type": asset_type, "n": 0, "views": [], "downloads": []})
            continue

        print(f"  {len(ids)} items: {ids}")
        views_for_type = []
        dls_for_type   = []

        for item_id in ids:
            try:
                counts = get_counts_from_html(asset_type, item_id)
            except Exception as exc:
                print(f"  Error fetching {asset_type}/{item_id}: {exc}")
                errors.append(f"{asset_type}/{item_id}: {exc}")
                continue

            if counts is None:
                errors.append(f"{asset_type}/{item_id}: could not parse counts")
                continue

            print(f"  {asset_type}/{item_id}: views={counts['views']}, downloads={counts['downloads']}")
            views_for_type.append(counts["views"])
            dls_for_type.append(counts["downloads"])

        type_summary.append({
            "type": asset_type,
            "n": len(views_for_type),
            "views": views_for_type,
            "downloads": dls_for_type,
        })
        all_views.extend(views_for_type)
        all_downloads.extend(dls_for_type)

    # ── Statistics ──────────────────────────────────────────────────────────────
    views_stats = compute_stats(all_views)
    dls_stats   = compute_stats(all_downloads)

    # ── Report ─────────────────────────────────────────────────────────────────
    n_total = views_stats["n"]

    lines = []
    lines.append("# ArmLifeBank Access & Download Statistics")
    lines.append("")
    lines.append(f"**Snapshot date:** {SNAPSHOT}")
    lines.append(f"**Asset types included:** {', '.join(ASSET_TYPES)}")
    lines.append(f"**Total items (n):** {n_total}")
    lines.append("")
    lines.append("## Comparison table")
    lines.append("")
    lines.append("| Platform | Metric | Mean | SD | Max |")
    lines.append("|---|---|---|---|---|")
    lines.append("| LHA | Download frequency | 28.60 | 59.52 | 1,019 |")
    lines.append("| LHA | Content accesses (crawlers excluded) | 77.89 | 114.53 | 1,229 |")

    def fmt(v):
        return str(v) if v is not None else "N/A"

    dls_max_fmt  = f"{dls_stats['max']:,}"   if dls_stats['max']   is not None else "N/A"
    views_max_fmt= f"{views_stats['max']:,}" if views_stats['max'] is not None else "N/A"

    lines.append(
        f"| ALB | Download frequency | {fmt(dls_stats['mean'])} | "
        f"{fmt(dls_stats['sd'])} | {dls_max_fmt} |"
    )
    lines.append(
        f"| ALB | Content accesses (**NOT** crawler-excluded — see note) | "
        f"{fmt(views_stats['mean'])} | {fmt(views_stats['sd'])} | {views_max_fmt} |"
    )
    lines.append("")
    lines.append("## ALB figures: n and per-type breakdown")
    lines.append("")
    lines.append("| Asset type | n | Mean views | Mean downloads |")
    lines.append("|---|---|---|---|")
    for ts in type_summary:
        vs = compute_stats(ts["views"])
        ds = compute_stats(ts["downloads"])
        lines.append(
            f"| {ts['type']} | {ts['n']} | "
            f"{fmt(vs['mean'])} | {fmt(ds['mean'])} |"
        )
    lines.append("")
    lines.append("## API field names")
    lines.append("")
    lines.append(
        "The SEEK JSON API (`/data_files/N.json`, etc.) does **not** expose view or "
        "download counts in its response attributes. Counts were read from the HTML "
        "Activity panel on each item's page, specifically the `<p id=\"usage_count\">` "
        "element containing `Views: N` and `Downloads: N`."
    )
    lines.append("")
    lines.append("## Crawler-exclusion note")
    lines.append("")
    lines.append(
        "**Limitation:** SEEK's stored view count partially filters bots but does not "
        "apply a documented crawler exclusion list comparable to the LHA methodology. "
        "The 'Content accesses' figure above is therefore **not strictly crawler-excluded** "
        "and may be inflated relative to the LHA figure. It should be treated as an "
        "upper bound and labeled accordingly in any publication."
    )

    if errors:
        lines.append("")
        lines.append("## Errors / warnings")
        lines.append("")
        for e in errors:
            lines.append(f"- {e}")

    report = "\n".join(lines) + "\n"
    out_path = OUTPUT_DIR / "alb_stats.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\n\nOutput written to {out_path}")
    print("\n--- SUMMARY ---")
    print(f"n={n_total}")
    print(f"Downloads:  mean={dls_stats['mean']}, sd={dls_stats['sd']}, max={dls_stats['max']}")
    print(f"Views (raw): mean={views_stats['mean']}, sd={views_stats['sd']}, max={views_stats['max']}")


if __name__ == "__main__":
    main()
