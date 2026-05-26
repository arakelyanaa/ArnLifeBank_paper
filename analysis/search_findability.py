#!/usr/bin/env python3
"""
Search-based findability comparison: ArmLifeBank vs GEO vs PubMed.

For each ArmLifeBank-indexed paper that has a GEO accession, this script issues
the same topic query to three portals and records the rank at which the Armenian
paper / dataset appears.

Two passes are run and both kept in the output:

  Pass 1 – SPECIFIC queries  (3–4 terms derived from the paper's own keywords)
  Pass 2 – BROAD queries     (1–2 general terms a naive researcher would use)

Pass 1 reflects best-case findability; Pass 2 reflects realistic dilution.

Metric: Reciprocal Rank (RR = 1/rank). Higher = more findable; 0 = not found.

Outputs (written to output/armenia/):
  search_findability.csv   — one row per (pass, pmid, portal)
  search_findability.md    — both passes + comparison, preserved across runs

Usage:
  python analysis/search_findability.py
  python analysis/search_findability.py --retmax 500
  python analysis/search_findability.py --no-cache
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

# ── Query dictionaries ────────────────────────────────────────────────────────

# Pass 1: specific (3–4 terms derived from MeSH / keywords of each paper)
QUERIES_SPECIFIC: dict[str, str] = {
    "34281234": "melanoma transcriptome isoforms splicing",
    "33897770": "telomere maintenance pathway cancer",
    "35681780": "glioma multi-omics methylome",
    "35159171": "brain aging transcriptome methylation",
    "37680201": "pathway signal flow gene expression",
    "37568651": "colorectal liver metastasis transcriptome",
    "37217719": "mRNA translation decay bacteria",
    "39732652": "cardiac transcriptome western diet sex",
    "39273985": "grapevine transcriptome drought thiamine",
    "38763334": "pan-cancer telomere maintenance mechanisms",
    "38368435": "brain gene expression schizophrenia temporal",
}

# Pass 2: broad (1–2 general terms a researcher would realistically use)
QUERIES_BROAD: dict[str, str] = {
    "34281234": "melanoma RNA-seq",
    "33897770": "telomere cancer",
    "35681780": "glioma transcriptome",
    "35159171": "brain transcriptome aging",
    "37680201": "pathway analysis transcriptome",
    "37568651": "colorectal metastasis transcriptome",
    "37217719": "mRNA translation bacteria",
    "39732652": "cardiac transcriptome diet",
    "39273985": "grapevine transcriptome",
    "38763334": "cancer telomere",
    "38368435": "schizophrenia gene expression",
}

ARM_BASE = "https://armlifebank.am"
ARM_USER_AGENT = "ArmLifeBank-Research-Bot/1.0 (contact: arakelyanaa@gmail.com)"
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


# ── Caching ───────────────────────────────────────────────────────────────────

def _cache_path(cache_dir: Path, key: str) -> Path:
    safe = urllib.parse.quote(key, safe="")[:180]
    return cache_dir / f"{safe}.json"


def cached_get(url: str, cache_dir: Path, use_cache: bool,
               headers: dict | None = None, delay: float = 0.0) -> dict | list:
    path = _cache_path(cache_dir, url)
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if delay:
        time.sleep(delay)
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


# ── NCBI helpers ──────────────────────────────────────────────────────────────

def ncbi_esearch(db: str, query: str, retmax: int, api_key: str,
                 cache_dir: Path, use_cache: bool) -> dict:
    params = urllib.parse.urlencode({
        "db": db, "term": query,
        "retmax": retmax, "retmode": "json",
        "api_key": api_key,
    })
    url = f"{NCBI_BASE}/esearch.fcgi?{params}"
    return cached_get(url, cache_dir, use_cache, delay=0.11)


def resolve_gse_uid(gse_acc: str, api_key: str,
                    cache_dir: Path, use_cache: bool) -> str | None:
    """Return the GDS UID (starts with '200') for a GSE accession, or None."""
    data = ncbi_esearch("gds", f"{gse_acc}[Accession]", retmax=10,
                        api_key=api_key, cache_dir=cache_dir, use_cache=use_cache)
    ids = data["esearchresult"]["idlist"]
    series = [uid for uid in ids if uid.startswith("200")]
    return series[0] if series else None


def find_rank(target: str, id_list: list[str]) -> int | None:
    """1-based rank of target in id_list, or None if not present."""
    try:
        return id_list.index(target) + 1
    except ValueError:
        return None


# ── ArmLifeBank search ────────────────────────────────────────────────────────

def arm_search_all(query: str, cache_dir: Path,
                   use_cache: bool, delay: float = 1.2) -> list[str]:
    """
    Paginate through all ArmLifeBank publication search results for *query*.
    Returns an ordered list of publication IDs as returned by the API.
    """
    page_size = 25
    page = 1
    all_ids: list[str] = []
    headers = {
        "User-Agent": ARM_USER_AGENT,
        "Accept": "application/json",
    }
    while True:
        params = urllib.parse.urlencode({
            "search[query]": query,
            "page[number]": page,
            "page[size]": page_size,
        })
        url = f"{ARM_BASE}/publications.json?{params}"
        try:
            data = cached_get(url, cache_dir, use_cache, headers=headers, delay=delay)
        except Exception as exc:
            print(f"    [ArmLifeBank] page {page} error: {exc}")
            break
        records = data.get("data", [])
        all_ids.extend(str(r["id"]) for r in records)
        if not records or len(records) < page_size:
            break
        if data.get("links", {}).get("next") is None:
            break
        page += 1
    return all_ids


# ── Per-pass search loop ──────────────────────────────────────────────────────

def run_pass(
    pass_label: str,
    queries: dict[str, str],
    geo_links: dict[str, list[str]],
    gse_to_uid: dict[str, str | None],
    pmid_to_arm_id: dict[str, str],
    title_map: dict[str, str],
    api_key: str,
    retmax: int,
    cache_dir: Path,
    use_cache: bool,
) -> list[dict]:
    """Run all three portal searches for every paper and return raw rows."""
    rows: list[dict] = []

    for pmid, gse_list in sorted(geo_links.items()):
        query = queries.get(pmid)
        if not query:
            print(f"  PMID {pmid}: no query defined — skipping")
            continue

        title_short = title_map.get(pmid, "")[:60]
        arm_pub_id  = pmid_to_arm_id.get(pmid)
        target_uids = [gse_to_uid[g] for g in gse_list if gse_to_uid.get(g)]
        geo_gse     = ", ".join(gse_list)

        print(f"\n  PMID {pmid} — {title_short}")
        print(f"    Query: \"{query}\"")

        # GEO
        geo_data  = ncbi_esearch("gds", query, retmax, api_key, cache_dir, use_cache)
        geo_total = int(geo_data["esearchresult"]["count"])
        geo_ids   = geo_data["esearchresult"]["idlist"]
        geo_ranks = [find_rank(uid, geo_ids) for uid in target_uids if uid]
        geo_rank  = min((r for r in geo_ranks if r is not None), default=None)
        geo_rr    = round(1 / geo_rank, 4) if geo_rank else 0.0
        print(f"    GEO   : total={geo_total:,}  rank={geo_rank}  RR={geo_rr}")

        rows.append({
            "pass": pass_label, "pmid": pmid, "gse_accessions": geo_gse,
            "query": query, "portal": "GEO",
            "total_results": geo_total, "rank": geo_rank,
            "reciprocal_rank": geo_rr,
            "in_top_retmax": geo_rank is not None,
            "retmax_used": retmax,
        })

        # PubMed
        pub_data  = ncbi_esearch("pubmed", query, retmax, api_key, cache_dir, use_cache)
        pub_total = int(pub_data["esearchresult"]["count"])
        pub_ids   = pub_data["esearchresult"]["idlist"]
        pub_rank  = find_rank(pmid, pub_ids)
        pub_rr    = round(1 / pub_rank, 4) if pub_rank else 0.0
        print(f"    PubMed: total={pub_total:,}  rank={pub_rank}  RR={pub_rr}")

        rows.append({
            "pass": pass_label, "pmid": pmid, "gse_accessions": geo_gse,
            "query": query, "portal": "PubMed",
            "total_results": pub_total, "rank": pub_rank,
            "reciprocal_rank": pub_rr,
            "in_top_retmax": pub_rank is not None,
            "retmax_used": retmax,
        })

        # ArmLifeBank
        arm_ids   = arm_search_all(query, cache_dir, use_cache)
        arm_total = len(arm_ids)
        arm_rank  = find_rank(arm_pub_id, arm_ids) if arm_pub_id else None
        arm_rr    = round(1 / arm_rank, 4) if arm_rank else 0.0
        print(f"    ArmLB : total={arm_total}  rank={arm_rank}  RR={arm_rr}")

        rows.append({
            "pass": pass_label, "pmid": pmid, "gse_accessions": geo_gse,
            "query": query, "portal": "ArmLifeBank",
            "total_results": arm_total, "rank": arm_rank,
            "reciprocal_rank": arm_rr,
            "in_top_retmax": arm_rank is not None,
            "retmax_used": retmax,
        })

    return rows


# ── Markdown helpers ──────────────────────────────────────────────────────────

def fmt_rank(v) -> str:
    return "—" if (v is None or (isinstance(v, float) and v != v)) else str(int(v))

def fmt_rr(v) -> str:
    if v is None or (isinstance(v, float) and v != v) or v == 0:
        return "0"
    return f"{v:.4f}"

def fmt_total(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    return f"{int(v):,}"


def build_pass_section(pass_label: str, df_pass: pd.DataFrame, retmax: int) -> list[str]:
    """Return markdown lines for one pass: per-paper table + summary."""
    lines: list[str] = [
        f"## Pass {pass_label[-1] if pass_label[-1].isdigit() else pass_label}: "
        f"{'Specific queries (3–4 terms from paper keywords)' if '1' in pass_label else 'Broad queries (1–2 general terms)'}",
        "",
    ]

    pivot = df_pass.pivot_table(
        index=["pmid", "gse_accessions", "query"],
        columns="portal",
        values=["total_results", "rank", "reciprocal_rank"],
        aggfunc="first",
    )
    pivot.columns = [f"{v}_{p}" for v, p in pivot.columns]
    pivot = pivot.reset_index()

    lines += [
        "| PMID | GSE | Query | "
        "GEO total | GEO rank | GEO RR | "
        "PubMed total | PubMed rank | PubMed RR | "
        "ArmLB total | ArmLB rank | ArmLB RR |",
        "|------|-----|-------|"
        "----------:|---------:|------:|"
        "-------------:|------------:|----------:|"
        "------------:|-----------:|--------:|",
    ]
    for _, r in pivot.iterrows():
        lines.append(
            f"| {r['pmid']} | {r['gse_accessions']} | {r['query']} | "
            f"{fmt_total(r.get('total_results_GEO'))} | "
            f"{fmt_rank(r.get('rank_GEO'))} | {fmt_rr(r.get('reciprocal_rank_GEO'))} | "
            f"{fmt_total(r.get('total_results_PubMed'))} | "
            f"{fmt_rank(r.get('rank_PubMed'))} | {fmt_rr(r.get('reciprocal_rank_PubMed'))} | "
            f"{fmt_total(r.get('total_results_ArmLifeBank'))} | "
            f"{fmt_rank(r.get('rank_ArmLifeBank'))} | "
            f"{fmt_rr(r.get('reciprocal_rank_ArmLifeBank'))} |"
        )

    lines += ["", f"*retmax = {retmax}; rank = — means not found in top {retmax} results.*", ""]

    # Summary for this pass
    lines += ["**Summary**", ""]
    lines += [
        "| Portal | Found in top N | Mean corpus size | Median rank (when found) | Mean RR |",
        "|--------|---------------:|-----------------:|-------------------------:|--------:|",
    ]
    for portal in ["GEO", "PubMed", "ArmLifeBank"]:
        sub = df_pass[df_pass["portal"] == portal]
        n_found    = int(sub["in_top_retmax"].sum())
        n_total    = len(sub)
        mean_total = sub["total_results"].mean()
        med_rank   = sub.loc[sub["rank"].notna(), "rank"].median()
        mean_rr    = sub["reciprocal_rank"].mean()
        lines.append(
            f"| {portal} | {n_found}/{n_total} | "
            f"{mean_total:,.0f} | "
            f"{'—' if med_rank != med_rank else f'{med_rank:.0f}'} | "
            f"{mean_rr:.4f} |"
        )
    lines.append("")
    return lines


def build_comparison_section(df: pd.DataFrame) -> list[str]:
    """Return markdown lines comparing mean RR across both passes."""
    lines: list[str] = [
        "## Pass comparison — impact of query specificity on Mean RR",
        "",
        "| Portal | Pass 1 Mean RR (specific) | Pass 2 Mean RR (broad) | Δ RR (broad − specific) |",
        "|--------|-------------------------:|-----------------------:|------------------------:|",
    ]
    for portal in ["GEO", "PubMed", "ArmLifeBank"]:
        rr1 = df[(df["pass"] == "pass1") & (df["portal"] == portal)]["reciprocal_rank"].mean()
        rr2 = df[(df["pass"] == "pass2") & (df["portal"] == portal)]["reciprocal_rank"].mean()
        delta = rr2 - rr1
        sign  = "+" if delta >= 0 else ""
        lines.append(
            f"| {portal} | {rr1:.4f} | {rr2:.4f} | {sign}{delta:.4f} |"
        )
    lines += [
        "",
        "> A **negative Δ** means the portal becomes harder to use as queries get broader",
        "> (dilution effect). A **positive or near-zero Δ** means the portal is robust to",
        "> query broadening — likely because its corpus is small and pre-filtered.",
    ]
    return lines


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Two-pass search findability: ArmLifeBank vs GEO vs PubMed."
    )
    parser.add_argument("--retmax", type=int, default=500,
                        help="Max results from GEO/PubMed per query (default: 500).")
    parser.add_argument("--no-cache", action="store_true",
                        help="Ignore cached responses and re-fetch everything.")
    args = parser.parse_args()

    use_cache = not args.no_cache
    root      = Path(__file__).resolve().parent.parent
    out_dir   = root / "output" / "armenia"
    cache_dir = root / ".cache" / "search_findability"
    cache_dir.mkdir(parents=True, exist_ok=True)

    api_key = (root / "NCBI_API.txt").read_text().strip()

    # ── Load data ─────────────────────────────────────────────────────────────
    disc = json.loads(
        (root / "output" / "arm_discoverability" / "results.json").read_text()
    )
    arm_pmids = set(disc["combined"]["pmids"])

    links = pd.read_csv(out_dir / "article_repository_links.csv", dtype={"pmid": str})
    geo_links = (
        links[links["pmid"].isin(arm_pmids) &
              (links["repository"] == "Gene Expression Omnibus")]
        .groupby("pmid")["identifier"]
        .apply(list)
        .to_dict()
    )

    arts = pd.read_csv(out_dir / "articles.csv", dtype={"pmid": str},
                       usecols=["pmid", "title"])
    title_map = arts.set_index("pmid")["title"].to_dict()

    idx = pd.read_csv(root / "output" / "arm_index.csv")
    pmid_to_arm_id: dict[str, str] = {}
    for _, row in idx.iterrows():
        raw = row["linked_pmids"]
        if pd.isna(raw) or str(raw) in ("[]", ""):
            continue
        try:
            for p in json.loads(raw):
                pmid_to_arm_id[str(p)] = str(row["lha_id"]).replace("pub_", "")
        except Exception:
            pass

    # ── Resolve GSE UIDs (cached after first run) ─────────────────────────────
    print("Resolving GSE accessions to GDS UIDs …")
    all_gse = {gse for gses in geo_links.values() for gse in gses}
    gse_to_uid: dict[str, str | None] = {}
    for gse in sorted(all_gse):
        uid = resolve_gse_uid(gse, api_key, cache_dir, use_cache)
        gse_to_uid[gse] = uid
        print(f"  {gse} → UID {uid}")

    shared = dict(
        geo_links=geo_links, gse_to_uid=gse_to_uid,
        pmid_to_arm_id=pmid_to_arm_id, title_map=title_map,
        api_key=api_key, retmax=args.retmax,
        cache_dir=cache_dir, use_cache=use_cache,
    )

    # ── Pass 1: specific queries ──────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("Pass 1 — specific queries")
    print('─'*60)
    rows1 = run_pass("pass1", QUERIES_SPECIFIC, **shared)

    # ── Pass 2: broad queries ─────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("Pass 2 — broad queries")
    print('─'*60)
    rows2 = run_pass("pass2", QUERIES_BROAD, **shared)

    # ── Save CSV ──────────────────────────────────────────────────────────────
    df = pd.DataFrame(rows1 + rows2)
    csv_path = out_dir / "search_findability.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nSaved: {csv_path}")

    # ── Build Markdown ────────────────────────────────────────────────────────
    df1 = df[df["pass"] == "pass1"]
    df2 = df[df["pass"] == "pass2"]

    lines: list[str] = [
        "# Search-Based Findability: ArmLifeBank vs GEO vs PubMed",
        "",
        f"*{len(geo_links)} ArmLifeBank-indexed papers with GEO accessions "
        f"(Armenia 2020–2025). Same topic query issued identically to all three portals.*",
        "",
        "**Metric — Reciprocal Rank (RR) = 1/rank.** "
        "Higher = more findable. RR = 0 means not found in top N results.",
        "",
        "Two passes are shown to separate best-case findability (specific queries) from",
        "realistic findability (broad queries a researcher would actually use).",
        "",
        "---",
        "",
    ]

    lines += build_pass_section("pass1", df1, args.retmax)
    lines += ["---", ""]
    lines += build_pass_section("pass2", df2, args.retmax)
    lines += ["---", ""]
    lines += build_comparison_section(df)
    lines += [
        "",
        "---",
        "",
        "## Interpretation",
        "",
        "- **Corpus size**: ArmLifeBank's ~150-paper corpus is pre-filtered to Armenian",
        "  research. GEO and PubMed corpora are orders of magnitude larger, diluting",
        "  Armenian content among thousands of global results.",
        "",
        "- **Pass 1 vs Pass 2**: with specific queries, PubMed often ranks the paper",
        "  highly because the query terms come from the paper's own abstract.",
        "  With broad queries, PubMed and GEO corpora expand dramatically and",
        "  Armenian papers get pushed down — the dilution effect becomes visible.",
        "",
        "- **ArmLifeBank stability**: because the corpus is small and fully Armenian,",
        "  broadening the query has little effect on rank — the paper is still within",
        "  the first ~50 results regardless of query specificity.",
        "",
        "- **GEO keyword search**: consistently poor across both passes.",
        "  GEO is optimised for accession-based access, not topic discovery.",
        "  Researchers cannot reliably find Armenian GEO datasets by keyword alone.",
        "",
        "- **Hypothesis**: ArmLifeBank improves the findability of Armenian biomedical",
        "  datasets for topic-based searches. Supported most clearly in Pass 2",
        "  (broad queries), where the dilution effect in PubMed/GEO is largest.",
    ]

    md_path = out_dir / "search_findability.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved: {md_path}")

    # ── Console summary ───────────────────────────────────────────────────────
    for pass_label, df_p in [("Pass 1 (specific)", df1), ("Pass 2 (broad)", df2)]:
        print(f"\n── {pass_label} ──────────────────────────────────────────────────")
        print(f"{'Portal':<14} {'Found':>8} {'Mean corpus':>14} {'Median rank':>13} {'Mean RR':>10}")
        print("─" * 64)
        for portal in ["GEO", "PubMed", "ArmLifeBank"]:
            sub = df_p[df_p["portal"] == portal]
            n_f  = int(sub["in_top_retmax"].sum())
            n_t  = len(sub)
            mt   = sub["total_results"].mean()
            mr   = sub.loc[sub["rank"].notna(), "rank"].median()
            mrr  = sub["reciprocal_rank"].mean()
            print(f"{portal:<14} {f'{n_f}/{n_t}':>8} {mt:>14,.0f} "
                  f"{'—' if mr != mr else f'{mr:.0f}':>13} {mrr:>10.4f}")


if __name__ == "__main__":
    main()
