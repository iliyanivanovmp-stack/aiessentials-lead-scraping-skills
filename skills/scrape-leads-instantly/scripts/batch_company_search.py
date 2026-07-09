"""
Batch search for C-level leads across a list of companies.

Reads company names from a CSV export of a Google Sheet, searches Instantly
SuperSearch in batches of 20, filters results to confirmed target companies,
and writes a combined JSON file for write_sheet.py.

Usage:
    python3 scripts/batch_company_search.py \
        --companies companies.json \
        --output .tmp/batch_results.json \
        --limit_per_batch 100
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

BASE_URL = "https://api.instantly.ai/api/v2/supersearch-enrichment"
PAGE_SIZE = 25

SENIOR_LEVELS = [
    "Owner",
    "Chief X Officer (CxO)",
    "Vice President (VP)",
    "Director",
    "Executive",
]

SENIOR_TITLES = [
    "CEO", "Chief Executive Officer",
    "Founder", "Co-Founder", "Co Founder",
    "President",
    "Managing Director",
    "Director",
    "VP", "Vice President",
    "Head of",
]


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
        raise RuntimeError(f"curl failed: {result.stderr}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Invalid JSON: {result.stdout[:300]}", file=sys.stderr)
        raise
    if "error" in data or "statusCode" in data:
        raise RuntimeError(f"API error: {data}")
    return data


def normalize(name: str) -> str:
    """Lowercase, strip punctuation/legal suffixes for fuzzy company matching."""
    name = name.lower()
    name = re.sub(r'\b(llc|inc|ltd|co|corp|the|®|™)\b', '', name)
    name = re.sub(r'[^a-z0-9 ]', '', name)
    return ' '.join(name.split())


def lead_matches_batch(lead: dict, target_names_normalized: list[str]) -> bool:
    lead_company = normalize(lead.get("companyName", ""))
    if not lead_company:
        return False
    for target in target_names_normalized:
        if target and (target in lead_company or lead_company in target):
            return True
    return False


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


def fetch_batch(company_names: list[str], api_key: str, limit: int) -> list[dict]:
    search_filters = {
        "company_name": {"include": company_names},
        "level": SENIOR_LEVELS,
    }

    all_leads = []
    page = 0
    while len(all_leads) < limit:
        try:
            result = post(
                "preview-leads-from-supersearch",
                {"search_filters": search_filters, "page": page, "pageSize": PAGE_SIZE},
                api_key,
            )
        except RuntimeError as e:
            print(f"  API error on page {page}: {e}")
            break

        batch = result.get("leads", [])
        if not batch:
            break
        all_leads.extend(batch)
        total = result.get("number_of_leads", 0)
        print(f"  Page {page + 1}: {len(batch)} leads ({len(all_leads)}/{min(limit, total)} total in search)")
        if len(batch) < PAGE_SIZE:
            break
        page += 1
        time.sleep(0.4)

    return all_leads


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--companies", required=True, help="JSON file: list of {name, domain} objects")
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch_size", type=int, default=20)
    parser.add_argument("--limit_per_batch", type=int, default=150,
                        help="Max leads to fetch per batch before filtering")
    args = parser.parse_args()

    api_key = get_api_key()

    with open(args.companies) as f:
        companies = json.load(f)

    print(f"Processing {len(companies)} companies in batches of {args.batch_size}")

    all_rows = []
    seen_keys = set()
    company_hits = {c["domain"]: [] for c in companies}

    for i in range(0, len(companies), args.batch_size):
        batch = companies[i: i + args.batch_size]
        names = [c["name"] for c in batch]
        domains = [c["domain"] for c in batch]
        normalized_names = [normalize(n) for n in names]

        print(f"\nBatch {i // args.batch_size + 1}: companies {i+1}-{i+len(batch)}")
        print(f"  Searching: {', '.join(names[:5])}{'...' if len(names) > 5 else ''}")

        raw_leads = fetch_batch(names, api_key, args.limit_per_batch)
        print(f"  Raw leads returned: {len(raw_leads)}")

        # Filter to leads that actually match one of the batch companies
        matched = 0
        for lead in raw_leads:
            lead_co_norm = normalize(lead.get("companyName", ""))
            matched_domain = None
            for idx, norm_name in enumerate(normalized_names):
                if norm_name and (norm_name in lead_co_norm or lead_co_norm in norm_name):
                    matched_domain = domains[idx]
                    break

            if not matched_domain:
                continue

            # Dedup by LinkedIn or name+company
            key = (lead.get("linkedIn") or "").strip().lower() or (
                (lead.get("fullName") or "").lower() + "|" + (lead.get("companyName") or "").lower()
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)

            row = lead_to_row(lead, matched_domain)
            all_rows.append(row)
            company_hits[matched_domain].append(row)
            matched += 1

        print(f"  Matched to target companies: {matched}")
        time.sleep(0.5)

    # Summary
    print(f"\n{'='*60}")
    print(f"Total unique leads: {len(all_rows)}")
    hits_3plus = sum(1 for hits in company_hits.values() if len(hits) >= 3)
    hits_1_2 = sum(1 for hits in company_hits.values() if 1 <= len(hits) < 3)
    hits_0 = sum(1 for hits in company_hits.values() if len(hits) == 0)
    print(f"Companies with 3+ leads: {hits_3plus}")
    print(f"Companies with 1-2 leads: {hits_1_2}")
    print(f"Companies with 0 leads: {hits_0}")

    if hits_0 > 0:
        print("\nCompanies with NO leads found:")
        for domain, hits in company_hits.items():
            if len(hits) == 0:
                print(f"  {domain}")

    if hits_1_2 > 0:
        print("\nCompanies with only 1-2 leads:")
        for domain, hits in company_hits.items():
            if 1 <= len(hits) < 3:
                print(f"  {domain}: {len(hits)}")

    with open(args.output, "w") as f:
        json.dump({"mode": "people", "rows": all_rows}, f, indent=2)

    print(f"\nSaved {len(all_rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
