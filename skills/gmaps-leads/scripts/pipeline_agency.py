"""
Agency lead pipeline: Clutch.co → DesignRush → organic Google fallback.

Sources:
  1. Clutch.co  - SerpAPI finds category page, Firecrawl scrapes, regex parses
  2. DesignRush - same; already exposes real agency websites in its markdown
  3. Organic    - SerpAPI broad search + Firecrawl roundup pages; fires until limit hit

Website enrichment:
  Clutch profile pages don't expose the agency's external website.
  After scraping Clutch, a parallel SerpAPI lookup finds each agency's real website.
  DesignRush entries skip this - they already have real websites.
"""

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

import httpx

SERPAPI_URL = "https://serpapi.com/search.json"
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"

AGENCY_COLUMNS = [
    "business_name", "website", "location", "rating", "review_count",
    "min_project_size", "team_size", "source", "search_query", "scraped_at",
]

AGGREGATOR_DOMAINS = {"clutch.co", "designrush.com"}


def _serpapi_key() -> str:
    key = os.getenv("SERPAPI_KEY")
    if not key:
        print("Error: SERPAPI_KEY not set", file=sys.stderr)
        sys.exit(1)
    return key


def _firecrawl_key() -> str:
    key = os.getenv("FIRECRAWL_API_KEY")
    if not key:
        print("Error: FIRECRAWL_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    return key


def _get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "").lower()
    except Exception:
        return ""


def _is_aggregator(url: str) -> bool:
    return _get_domain(url) in AGGREGATOR_DOMAINS


# ── SerpAPI ───────────────────────────────────────────────────────────────────

def serpapi_search(query: str, num: int = 10) -> list[dict]:
    try:
        resp = httpx.get(
            SERPAPI_URL,
            params={"q": query, "api_key": _serpapi_key(), "num": num, "engine": "google"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("organic_results", [])
    except Exception as e:
        print(f"  SerpAPI error: {e}", file=sys.stderr)
        return []


def _find_agency_website(agency_name: str) -> str:
    """
    One SerpAPI search to find an agency's real website.
    Returns the first organic result that isn't an aggregator.
    """
    results = serpapi_search(f'"{agency_name}" agency official website', num=5)
    for r in results:
        url = r.get("link", "")
        domain = _get_domain(url)
        if domain and domain not in AGGREGATOR_DOMAINS and "." in domain:
            return url.split("?")[0].rstrip("/")
    return ""


def enrich_websites(agencies: list[dict], max_workers: int = 5) -> list[dict]:
    """
    For agencies where website is a Clutch/DesignRush profile URL,
    look up their real website in parallel via SerpAPI.
    """
    needs_enrichment = [a for a in agencies if _is_aggregator(a.get("website", ""))]
    if not needs_enrichment:
        return agencies

    print(f"  Enriching {len(needs_enrichment)} agencies with real websites (parallel)...")

    website_map: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_name = {
            executor.submit(_find_agency_website, a["business_name"]): a["business_name"]
            for a in needs_enrichment
        }
        done = 0
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                website = future.result()
                website_map[name] = website
            except Exception:
                website_map[name] = ""
            done += 1
            if done % 10 == 0 or done == len(needs_enrichment):
                print(f"  Website lookup: {done}/{len(needs_enrichment)}")

    for agency in agencies:
        if _is_aggregator(agency.get("website", "")):
            found = website_map.get(agency["business_name"], "")
            if found:
                agency["website"] = found

    return agencies


# ── Firecrawl ─────────────────────────────────────────────────────────────────

def firecrawl_markdown(url: str) -> str:
    try:
        resp = httpx.post(
            FIRECRAWL_SCRAPE_URL,
            headers={"Authorization": f"Bearer {_firecrawl_key()}", "Content-Type": "application/json"},
            json={"url": url, "formats": ["markdown"]},
            timeout=90,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("markdown", "") or ""
    except Exception as e:
        print(f"  Firecrawl error ({url}): {e}", file=sys.stderr)
        return ""


# ── Clutch parser ─────────────────────────────────────────────────────────────

def parse_clutch_markdown(md: str, query: str) -> list[dict]:
    blocks = re.split(r"(?=### \[)", md)
    results = []
    now = datetime.now().isoformat()

    for block in blocks[1:]:
        m_name = re.search(
            r"### \[([^\]]+)\]\((https://(?:r\.)?clutch\.co/[^\")\s]+)",
            block,
        )
        if not m_name:
            continue

        name = m_name.group(1).strip()
        raw_url = m_name.group(2)

        if "r.clutch.co/redirect" in raw_url:
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            profile_url = f"https://clutch.co/profile/{slug}"
        else:
            profile_slug = raw_url.split("/profile/")[-1].rstrip("/")
            profile_url = f"https://clutch.co/profile/{profile_slug}"

        m_rating = re.search(r"(?m)^\s*(\d+\.\d+)\s*$", block)
        rating = m_rating.group(1) if m_rating else ""

        m_reviews = re.search(r"\[(\d+)\\\\", block)
        review_count = m_reviews.group(1) if m_reviews else ""

        m_price = re.search(r"(\$[\d,]+\+)", block)
        min_project_size = m_price.group(1) if m_price else ""

        m_team = re.search(r"(\d{1,4}\s*-\s*\d{1,4})", block)
        team_size = m_team.group(1).replace(" ", "") if m_team else ""

        services_idx = block.find("Services provided")
        search_zone = block[:services_idx] if services_idx > 0 else block
        locations = re.findall(r"([A-Z][a-zA-Z\s\-]+,\s*[A-Z]{2,})", search_zone)
        location = locations[-1].strip() if locations else ""

        results.append({
            "business_name": name,
            "website": profile_url,   # real website filled in by enrich_websites()
            "location": location,
            "rating": rating,
            "review_count": review_count,
            "min_project_size": min_project_size,
            "team_size": team_size,
            "source": "clutch.co",
            "search_query": query,
            "scraped_at": now,
        })

    return results


def scrape_clutch(query: str, limit: int) -> list[dict]:
    serp_results = serpapi_search(f"{query} site:clutch.co/agencies", num=5)
    category_url = None
    for r in serp_results:
        link = r.get("link", "")
        if "clutch.co/agencies/" in link and "/profile/" not in link:
            category_url = link.split("?")[0]
            break

    if not category_url:
        print("  Could not find Clutch category URL.", file=sys.stderr)
        return []

    print(f"  Clutch category: {category_url}")
    agencies = []
    pages_needed = max(1, -(-limit // 80))

    for page in range(1, pages_needed + 1):
        url = category_url if page == 1 else f"{category_url}?page={page}"
        print(f"  Scraping Clutch page {page}...")
        md = firecrawl_markdown(url)
        if not md:
            break
        parsed = parse_clutch_markdown(md, query)
        if not parsed:
            break
        agencies.extend(parsed)
        if len(agencies) >= limit:
            break

    return agencies[:limit]


# ── DesignRush parser ─────────────────────────────────────────────────────────

def parse_designrush_markdown(md: str, query: str) -> list[dict]:
    now = datetime.now().isoformat()
    results = []
    blocks = re.split(r"(?=### \[)", md)

    for block in blocks[1:]:
        m_name = re.search(
            r'### \[([^\]]+)\]\((https?://[^")\s]+)\s*"VISIT WEBSITE"\)',
            block,
        )
        if not m_name:
            continue

        name = m_name.group(1).strip()
        website = m_name.group(2).split("?")[0].rstrip("/")

        m_rating = re.search(r"(\d+\.\d+)\s*(?:stars?|rating|/5)", block, re.IGNORECASE)
        rating = m_rating.group(1) if m_rating else ""

        m_reviews = re.search(r"(\d+)\s*[Rr]eview", block)
        review_count = m_reviews.group(1) if m_reviews else ""

        m_price = re.search(r"(\$[\d,]+\+)", block)
        min_project_size = m_price.group(1) if m_price else ""

        m_team = re.search(r"(\d{1,4}\s*[-–]\s*\d{1,4})", block)
        team_size = m_team.group(1).replace(" ", "") if m_team else ""

        locations = re.findall(r"([A-Z][a-zA-Z\s\-]+,\s*[A-Z]{2,})", block)
        location = locations[0].strip() if locations else ""

        results.append({
            "business_name": name,
            "website": website,
            "location": location,
            "rating": rating,
            "review_count": review_count,
            "min_project_size": min_project_size,
            "team_size": team_size,
            "source": "designrush.com",
            "search_query": query,
            "scraped_at": now,
        })

    return results


def scrape_designrush(query: str, limit: int) -> list[dict]:
    serp_results = serpapi_search(f"{query} site:designrush.com/agency", num=5)
    SKIP = ["/trends/", "/blog/", "/guide/", "/news/", "/profile/"]
    category_url = None
    for r in serp_results:
        link = r.get("link", "")
        if "designrush.com/agency/" in link and not any(p in link for p in SKIP):
            category_url = link.split("?")[0]
            break

    if not category_url:
        return []

    print(f"  DesignRush category: {category_url}")
    md = firecrawl_markdown(category_url)
    if not md:
        return []

    return parse_designrush_markdown(md, query)[:limit]


# ── Organic fallback ──────────────────────────────────────────────────────────

def organic_fallback(query: str, limit: int, seen_domains: set[str]) -> list[dict]:
    """
    SerpAPI broad search + scrape roundup pages.
    Continues until `limit` new results are collected.
    """
    results = []
    now = datetime.now().isoformat()

    queries = [
        f"best {query}",
        f"top {query} United States",
        f"leading {query} USA list",
    ]

    for q in queries:
        if len(results) >= limit:
            break

        serp = serpapi_search(q, num=10)

        for r in serp:
            if len(results) >= limit:
                break

            url = r.get("link", "")
            title = r.get("title", "")
            if not url or any(x in url for x in ["clutch.co", "designrush.com"]):
                continue

            domain = _get_domain(url)
            if domain in seen_domains:
                continue

            # Roundup pages: scrape and extract agency links
            if any(kw in title.lower() for kw in ["top", "best", "leading", "list"]):
                md = firecrawl_markdown(url)
                if not md:
                    continue
                agency_links = re.findall(
                    r"\[([^\]]{3,60})\]\((https?://(?!(?:clutch|designrush|google|youtube|linkedin|facebook|twitter|instagram|wikipedia)[^\)]+))[^\)]*\)",
                    md,
                )
                for ag_name, ag_url in agency_links[:30]:
                    ag_domain = _get_domain(ag_url)
                    if ag_domain and ag_domain not in seen_domains and "." in ag_domain:
                        seen_domains.add(ag_domain)
                        results.append({
                            "business_name": ag_name.strip(),
                            "website": ag_url.split("?")[0].rstrip("/"),
                            "location": "",
                            "rating": "",
                            "review_count": "",
                            "min_project_size": "",
                            "team_size": "",
                            "source": "organic",
                            "search_query": query,
                            "scraped_at": now,
                        })
                        if len(results) >= limit:
                            break
            else:
                # Treat the SERP result itself as an agency
                if domain and domain not in seen_domains:
                    seen_domains.add(domain)
                    results.append({
                        "business_name": title.split("|")[0].split("-")[0].strip(),
                        "website": url.split("?")[0].rstrip("/"),
                        "location": "",
                        "rating": "",
                        "review_count": "",
                        "min_project_size": "",
                        "team_size": "",
                        "source": "organic",
                        "search_query": query,
                        "scraped_at": now,
                    })

    return results[:limit]


# ── Main entry ────────────────────────────────────────────────────────────────

def search_agencies(query: str, limit: int = 20) -> list[dict]:
    """
    Clutch → DesignRush → organic. Enriches Clutch entries with real websites.
    Deduplicates by domain throughout (aggregator URLs keyed by full URL).
    """
    all_results: list[dict] = []
    seen: set[str] = set()          # domains (or full URLs for aggregator entries)
    seen_domains: set[str] = set()  # real domains only, for organic dedup

    def _key(r: dict) -> str:
        url = r.get("website", "")
        domain = _get_domain(url)
        return url if domain in AGGREGATOR_DOMAINS else (domain or r.get("business_name", "").lower().strip())

    def add_unique(batch: list[dict]) -> int:
        added = 0
        for r in batch:
            k = _key(r)
            if k and k not in seen:
                seen.add(k)
                d = _get_domain(r.get("website", ""))
                if d and d not in AGGREGATOR_DOMAINS:
                    seen_domains.add(d)
                all_results.append(r)
                added += 1
        return added

    # 1. Clutch
    print("  Searching Clutch.co...")
    clutch = scrape_clutch(query, limit)
    add_unique(clutch)
    print(f"  Clutch: {len(all_results)} unique agencies")

    # 2. DesignRush
    if len(all_results) < limit:
        print("  Searching DesignRush...")
        dr = scrape_designrush(query, limit - len(all_results))
        added_dr = add_unique(dr)
        print(f"  DesignRush: +{added_dr} → {len(all_results)} total")

    # 3. Organic fallback - keep running until limit hit
    if len(all_results) < limit:
        needed = limit - len(all_results)
        print(f"  Falling back to organic search (need {needed} more)...")
        organic = organic_fallback(query, needed, seen_domains)
        added_org = add_unique(organic)
        print(f"  Organic: +{added_org} → {len(all_results)} total")

    # 4. Enrich Clutch entries with real websites (parallel SerpAPI)
    if any(_is_aggregator(a.get("website", "")) for a in all_results):
        all_results = enrich_websites(all_results)

    return all_results[:limit]
