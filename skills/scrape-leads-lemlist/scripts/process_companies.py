"""
Merge and deduplicate lemleads_search results for Companies mode.

Input:  .tmp/raw_results.json  - {"pages": [{page response}, ...]}
Output: .tmp/processed.json   - {"mode": "companies", "rows": [[...], ...]}

Usage:
    python3 scripts/process_companies.py .tmp/raw_results.json --output .tmp/processed.json
"""
import argparse
import json
import sys


def company_identity_key(company: dict) -> str:
    domain = (company.get("domain") or company.get("website") or "").strip().lower()
    if domain:
        return f"domain:{domain}"
    name = (company.get("name") or company.get("company_name") or "").strip().lower()
    return f"name:{name}"


def dedupe(companies: list) -> list:
    seen = set()
    out = []
    for c in companies:
        key = company_identity_key(c)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def company_to_row(c: dict) -> list:
    return [
        c.get("name") or c.get("company_name") or "",
        c.get("domain") or c.get("website") or "",
        c.get("industry") or "",
        c.get("location") or c.get("country") or "",
        c.get("headcount") or c.get("employeeCount") or "",
        c.get("annualRevenue") or c.get("revenue") or "",
        c.get("website") or c.get("domain") or "",
        c.get("description") or "",
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Path to raw_results.json")
    parser.add_argument("--output", required=True, help="Path to write processed JSON")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    if isinstance(data, dict) and "pages" in data:
        all_companies = []
        for page in data["pages"]:
            all_companies.extend(page.get("results", []))
    elif isinstance(data, list):
        all_companies = data
    else:
        print("Unexpected input format", file=sys.stderr)
        sys.exit(1)

    unique = dedupe(all_companies)
    rows = [company_to_row(c) for c in unique]

    with open(args.output, "w") as f:
        json.dump({"mode": "companies", "rows": rows}, f, indent=2)

    print(f"Companies: {len(rows)} unique records")


if __name__ == "__main__":
    main()
