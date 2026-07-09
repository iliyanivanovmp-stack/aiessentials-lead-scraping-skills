"""
Search Apollo.io people or companies via REST API.

Usage:
    # People search
    python3 scripts/search_apollo.py --mode people \
        --filters '{"person_titles": ["CEO", "Founder"], "person_seniorities": ["c_suite", "owner"]}' \
        --limit 200 \
        --output .tmp/results.json

    # Company search
    python3 scripts/search_apollo.py --mode companies \
        --filters '{"q_organization_keyword_tags": ["saas"], "organization_num_employees_ranges": ["11,50"]}' \
        --limit 100 \
        --output .tmp/results.json

    # Count only (people)
    python3 scripts/search_apollo.py --mode people --count_only \
        --filters '{"person_titles": ["CEO"]}' \
        --output .tmp/results.json
"""
import argparse
import json
import os
import subprocess
import sys
import time

BASE_URL = "https://api.apollo.io/api/v1"
PAGE_SIZE = 100  # Apollo max is 100 per page


def get_api_key() -> str:
    key = os.environ.get("APOLLO_API_KEY", "").strip()
    if not key:
        env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    if line.startswith("APOLLO_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        break
    if not key:
        print("Error: APOLLO_API_KEY not found in environment or .env file", file=sys.stderr)
        sys.exit(1)
    return key


def post(endpoint: str, payload: dict, api_key: str) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    result = subprocess.run(
        [
            "curl", "-s", "-X", "POST", url,
            "-H", f"X-Api-Key: {api_key}",
            "-H", "Content-Type: application/json",
            "-H", "Cache-Control: no-cache",
            "-d", json.dumps(payload),
            "--max-time", "30",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"curl error: {result.stderr}", file=sys.stderr)
        raise RuntimeError("curl failed")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Invalid JSON response: {result.stdout[:300]}", file=sys.stderr)
        raise
    if "error" in data:
        print(f"API error: {data}", file=sys.stderr)
        raise RuntimeError(f"API error: {data.get('message', data)}")
    return data


def person_to_row(p: dict) -> list:
    org = p.get("organization") or {}
    first = p.get("first_name", "")
    last_partial = p.get("last_name_obfuscated", "") or p.get("last_name", "")
    has_email = "yes" if p.get("has_email") else "no"
    has_phone = "yes" if p.get("has_direct_phone") == "Yes" else "no"
    loc_parts = []
    if p.get("has_city"):
        loc_parts.append("city")
    if p.get("has_country"):
        loc_parts.append("country")
    return [
        f"{first} {last_partial}".strip(),
        p.get("title", ""),
        org.get("name", ""),
        has_email,
        has_phone,
        p.get("id", ""),
    ]


def company_to_row(c: dict) -> list:
    return [
        c.get("name", ""),
        c.get("website_url", "") or c.get("domain", ""),
        c.get("industry", ""),
        _org_loc(c),
        str(c.get("estimated_num_employees", "") or ""),
        c.get("annual_revenue_printed", "") or str(c.get("annual_revenue", "") or ""),
        c.get("short_description", "") or c.get("seo_description", ""),
    ]


def _org_loc(c: dict) -> str:
    parts = [c.get("city"), c.get("state"), c.get("country")]
    return ", ".join(x for x in parts if x)


def dedupe(items: list, key_fn) -> list:
    seen = set()
    out = []
    for item in items:
        k = key_fn(item)
        if k and k not in seen:
            seen.add(k)
            out.append(item)
    return out


def search_people(filters: dict, page: int, api_key: str) -> dict:
    payload = {"page": page, "per_page": PAGE_SIZE, **filters}
    return post("mixed_people/api_search", payload, api_key)


def search_companies(filters: dict, page: int, api_key: str) -> dict:
    payload = {"page": page, "per_page": PAGE_SIZE, **filters}
    return post("mixed_companies/search", payload, api_key)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["people", "companies"], required=True)
    parser.add_argument("--filters", required=True, help="JSON string of Apollo search filters")
    parser.add_argument("--limit", type=int, default=200, help="Max records to fetch")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--count_only", action="store_true", help="Only show total count, don't fetch")
    args = parser.parse_args()

    api_key = get_api_key()

    try:
        filters = json.loads(args.filters)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in --filters: {e}", file=sys.stderr)
        sys.exit(1)

    # Count-only: fetch page 1 just for the total
    if args.count_only:
        if args.mode == "people":
            data = search_people(filters, 1, api_key)
        else:
            data = search_companies(filters, 1, api_key)
        total = data.get("total_entries", 0)
        print(f"Total matching records: {total:,}")
        return

    all_items = []
    page = 1
    total = None

    while len(all_items) < args.limit:
        try:
            if args.mode == "people":
                data = search_people(filters, page, api_key)
                batch = data.get("people", [])
            else:
                data = search_companies(filters, page, api_key)
                batch = data.get("organizations", [])
        except RuntimeError:
            if page > 1:
                print(f"Stopping after page {page - 1} due to API error. Got {len(all_items)} records so far.")
                break
            sys.exit(1)

        if total is None:
            total = data.get("total_entries", 0)

        if not batch:
            break

        all_items.extend(batch)
        print(f"Page {page}: fetched {len(batch)} records ({len(all_items)}/{min(args.limit, total)} total)")

        if len(batch) < PAGE_SIZE:
            break

        page += 1
        time.sleep(0.5)  # stay well under rate limits

    truncated = all_items[: args.limit]

    if args.mode == "people":
        unique = dedupe(truncated, lambda p: (p.get("linkedin_url") or "").strip().lower()
                        or f"{p.get('first_name', '')} {p.get('last_name', '')}|{(p.get('organization') or {}).get('name', '')}".lower())
        rows = [person_to_row(p) for p in unique]
        mode_out = "people"
    else:
        unique = dedupe(truncated, lambda c: (c.get("website_url") or c.get("domain") or c.get("name", "")).lower())
        rows = [company_to_row(c) for c in unique]
        mode_out = "companies"

    os.makedirs(os.path.dirname(args.output), exist_ok=True) if os.path.dirname(args.output) else None
    with open(args.output, "w") as f:
        json.dump({"mode": mode_out, "rows": rows}, f, indent=2)

    print(f"\nDone: {len(rows)} unique {mode_out} saved to {args.output}")


if __name__ == "__main__":
    main()
