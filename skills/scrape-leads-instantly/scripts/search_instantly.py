"""
Search Instantly SuperSearch lead database via REST API.

Usage:
    python3 scripts/search_instantly.py \
        --filters '{"title": {"include": ["CEO"]}, "locations": [{"country": "United States"}]}' \
        --limit 200 \
        --output .tmp/results.json

    # Exact company domain search
    python3 scripts/search_instantly.py \
        --filters '{"domains": ["example.com"]}' \
        --limit 200 \
        --output .tmp/results.json

    python3 scripts/search_instantly.py --count_only \
        --filters '{"title": {"include": ["CEO"]}}' \
        --output .tmp/results.json
"""
import argparse
import json
import os
import subprocess
import sys
import time

BASE_URL = "https://api.instantly.ai/api/v2/supersearch-enrichment"
PAGE_SIZE = 25


def get_api_key() -> str:
    key = os.environ.get("INSTANTLY_API_KEY", "").strip()
    if not key:
        env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    if line.startswith("INSTANTLY_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        break
    if not key:
        print("Error: INSTANTLY_API_KEY not found in environment or .env file", file=sys.stderr)
        sys.exit(1)
    return key


def post(endpoint: str, payload: dict, api_key: str) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    result = subprocess.run(
        [
            "curl", "-s", "-X", "POST", url,
            "-H", f"Authorization: Bearer {api_key}",
            "-H", "Content-Type: application/json",
            "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
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
        print(f"Invalid JSON response: {result.stdout[:200]}", file=sys.stderr)
        raise
    if "error" in data or "statusCode" in data:
        print(f"API error: {data}", file=sys.stderr)
        raise RuntimeError(f"API error: {data.get('message', data)}")
    return data


def lead_to_row(lead: dict, source_domain: str = "") -> list:
    return [
        lead.get("fullName") or f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip(),
        lead.get("jobTitle", ""),
        lead.get("companyName", ""),
        lead.get("location", ""),
        lead.get("linkedIn", ""),
        source_domain,
        str(lead.get("companyId", "")),
    ]


def dedupe(leads: list) -> list:
    seen = set()
    out = []
    for lead in leads:
        key = (
            (lead.get("linkedIn") or "").strip().lower()
            or (lead.get("fullName") or "").strip().lower() + "|" + (lead.get("companyName") or "").strip().lower()
        )
        if key and key not in seen:
            seen.add(key)
            out.append(lead)
    return out


def count_leads(search_filters: dict, api_key: str) -> int:
    result = post("count-leads-from-supersearch", {"search_filters": search_filters}, api_key)
    return result.get("number_of_leads", 0)


def preview_page(search_filters: dict, page: int, api_key: str) -> dict:
    payload = {
        "search_filters": search_filters,
        "page": page,
        "pageSize": PAGE_SIZE,
    }
    return post("preview-leads-from-supersearch", payload, api_key)


def source_domain_from_filters(search_filters: dict) -> str:
    domains = search_filters.get("domains")
    if isinstance(domains, list) and len(domains) == 1:
        return str(domains[0]).strip()
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filters", required=True, help="JSON string of search_filters")
    parser.add_argument("--limit", type=int, default=200, help="Max leads to fetch")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument("--count_only", action="store_true", help="Only count, don't fetch")
    args = parser.parse_args()

    api_key = get_api_key()

    try:
        search_filters = json.loads(args.filters)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in --filters: {e}", file=sys.stderr)
        sys.exit(1)

    if args.count_only:
        count = count_leads(search_filters, api_key)
        print(f"Total matching leads: {count:,}")
        return

    all_leads = []
    page = 0
    while len(all_leads) < args.limit:
        try:
            result = preview_page(search_filters, page, api_key)
        except RuntimeError:
            if page > 0:
                print(f"Stopping after page {page} due to API error. Got {len(all_leads)} leads so far.")
                break
            sys.exit(1)

        batch = result.get("leads", [])
        if not batch:
            break

        all_leads.extend(batch)
        total = result.get("number_of_leads", 0)
        print(f"Page {page + 1}: fetched {len(batch)} leads ({len(all_leads)}/{min(args.limit, total)} total)")

        if len(batch) < PAGE_SIZE:
            break

        page += 1
        time.sleep(0.3)

    unique = dedupe(all_leads[: args.limit])
    source_domain = source_domain_from_filters(search_filters)
    rows = [lead_to_row(lead, source_domain) for lead in unique]

    with open(args.output, "w") as f:
        json.dump({"mode": "people", "rows": rows}, f, indent=2)

    print(f"\nDone: {len(rows)} unique leads saved to {args.output}")


if __name__ == "__main__":
    main()
