"""
Targeted search for individual companies that have <3 leads.
Searches each company domain individually with a high limit to maximize coverage.

Usage:
    python3 scripts/targeted_company_search.py \
        --companies .tmp/companies.json \
        --existing .tmp/batch_results.json \
        --output .tmp/all_results.json \
        --min_leads 3
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
    result = subprocess.run(
        [
            "curl", "-s", "-X", "POST", f"{BASE_URL}/{endpoint}",
            "-H", f"Authorization: Bearer {api_key}",
            "-H", "Content-Type: application/json",
            "-H", "User-Agent: Mozilla/5.0",
            "-d", json.dumps(payload),
            "--max-time", "30",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Invalid JSON: {result.stdout[:200]}")
    if "error" in data or "statusCode" in data:
        raise RuntimeError(f"API error: {data}")
    return data


def normalize(name: str) -> str:
    name = name.lower()
    name = re.sub(r'\b(llc|inc|ltd|co|corp|the|hcp|us|usa)\b', '', name)
    name = re.sub(r'[^a-z0-9 ]', '', name)
    return ' '.join(name.split())


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


def search_one_company(domain: str, api_key: str, limit: int = 100) -> list[dict]:
    search_filters = {
        "domains": [domain],
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
            print(f"    Error on page {page}: {e}")
            break
        batch = result.get("leads", [])
        if not batch:
            break
        all_leads.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
        time.sleep(0.3)
    return all_leads


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--companies", required=True)
    parser.add_argument("--existing", required=True, help="Existing results JSON from batch_company_search.py")
    parser.add_argument("--output", required=True)
    parser.add_argument("--min_leads", type=int, default=3, help="Target minimum leads per company")
    args = parser.parse_args()

    api_key = get_api_key()

    with open(args.companies) as f:
        companies = json.load(f)

    with open(args.existing) as f:
        existing = json.load(f)

    existing_rows = existing.get("rows", [])

    # Count existing leads per domain (domain is column index 5)
    company_hits: dict[str, list] = {c["domain"]: [] for c in companies}
    for row in existing_rows:
        domain = row[5] if len(row) > 5 else ""
        if domain in company_hits:
            company_hits[domain].append(row)

    # Dedup keys from existing
    seen_keys: set[str] = set()
    for row in existing_rows:
        linkedin = row[4].strip().lower() if len(row) > 4 else ""
        name_co = f"{row[0].lower()}|{row[2].lower()}"
        key = linkedin or name_co
        if key:
            seen_keys.add(key)

    # Find companies that need more leads
    needs_more = [c for c in companies if len(company_hits.get(c["domain"], [])) < args.min_leads]
    print(f"\nCompanies needing more leads (<{args.min_leads}): {len(needs_more)}")

    new_rows = []
    for i, company in enumerate(needs_more):
        domain = company["domain"]
        name = company["name"]
        existing_count = len(company_hits.get(domain, []))
        needed = args.min_leads - existing_count

        print(f"\n[{i+1}/{len(needs_more)}] {name} (has {existing_count}, need {needed} more)")

        found_new = 0
        raw = search_one_company(domain, api_key, limit=100)
        if not raw:
            print(f"  '{domain}': 0 results")
            continue

        matched = 0
        for lead in raw:
            linkedin = (lead.get("linkedIn") or "").strip().lower()
            name_co = f"{(lead.get('fullName') or '').lower()}|{(lead.get('companyName') or '').lower()}"
            key = linkedin or name_co
            if key in seen_keys:
                continue
            seen_keys.add(key)

            row = lead_to_row(lead, domain)
            company_hits[domain].append(row)
            new_rows.append(row)
            matched += 1
            found_new += 1

        total_now = len(company_hits[domain])
        print(f"  '{domain}': {len(raw)} raw → {matched} new matches (total: {total_now})")

        time.sleep(0.4)

    # Final tally
    all_rows = existing_rows + new_rows
    hits_3plus = sum(1 for hits in company_hits.values() if len(hits) >= 3)
    hits_1_2 = sum(1 for hits in company_hits.values() if 1 <= len(hits) < 3)
    hits_0 = sum(1 for hits in company_hits.values() if len(hits) == 0)

    print(f"\n{'='*60}")
    print(f"New leads found in this pass: {len(new_rows)}")
    print(f"Total unique leads: {len(all_rows)}")
    print(f"Companies with 3+ leads: {hits_3plus}/81")
    print(f"Companies with 1-2 leads: {hits_1_2}")
    print(f"Companies with 0 leads:   {hits_0}")

    if hits_0 > 0:
        print("\nStill no leads:")
        for domain, hits in company_hits.items():
            if len(hits) == 0:
                print(f"  {domain}")

    with open(args.output, "w") as f:
        json.dump({"mode": "people", "rows": all_rows}, f, indent=2)

    print(f"\nSaved {len(all_rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
