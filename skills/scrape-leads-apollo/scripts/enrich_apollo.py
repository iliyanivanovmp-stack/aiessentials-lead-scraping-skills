"""
Enrich Apollo people from search results using their Apollo IDs.

Usage:
    # Enrich all leads in results.json
    python3 scripts/enrich_apollo.py .tmp/results.json --output .tmp/enriched.json

    # Enrich only the first 50
    python3 scripts/enrich_apollo.py .tmp/results.json --output .tmp/enriched.json --limit 50

    # Enrich specific records by row index (0-based)
    python3 scripts/enrich_apollo.py .tmp/results.json --output .tmp/enriched.json --rows 0,1,2,5,10
"""
import argparse
import json
import os
import subprocess
import sys
import time

BASE_URL = "https://api.apollo.io/api/v1"
APOLLO_ID_COL = 5  # index of apollo_id in people row


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
        print("Error: APOLLO_API_KEY not found", file=sys.stderr)
        sys.exit(1)
    return key


def match_person(apollo_id: str, api_key: str) -> dict:
    payload = {
        "id": apollo_id,
        "reveal_personal_emails": False,
        "reveal_phone_number": False,
    }
    result = subprocess.run(
        [
            "curl", "-s", "-X", "POST", f"{BASE_URL}/people/match",
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
        raise RuntimeError(f"curl failed: {result.stderr}")
    data = json.loads(result.stdout)
    if "error" in data:
        raise RuntimeError(f"API error: {data}")
    return data.get("person", {})


def person_to_enriched_row(p: dict) -> list:
    org = p.get("organization") or {}
    return [
        p.get("name", "") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
        p.get("title", ""),
        org.get("name", ""),
        org.get("website_url", "") or org.get("primary_domain", ""),
        p.get("formatted_address", "") or ", ".join(filter(None, [p.get("city"), p.get("state"), p.get("country")])),
        p.get("linkedin_url", ""),
        p.get("email", ""),
        p.get("email_status", ""),
        str(org.get("estimated_num_employees", "") or ""),
        org.get("annual_revenue_printed", "") or str(org.get("annual_revenue", "") or ""),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Path to search results JSON (from search_apollo.py)")
    parser.add_argument("--output", required=True, help="Output path for enriched results")
    parser.add_argument("--limit", type=int, help="Enrich only the first N records")
    parser.add_argument("--rows", help="Comma-separated 0-based row indices to enrich (e.g. 0,1,4)")
    args = parser.parse_args()

    api_key = get_api_key()

    with open(args.input) as f:
        data = json.load(f)

    rows = data.get("rows", [])
    if not rows:
        print("No rows found in input.", file=sys.stderr)
        sys.exit(1)

    # Select subset
    if args.rows:
        indices = [int(i.strip()) for i in args.rows.split(",")]
        selected = [(i, rows[i]) for i in indices if i < len(rows)]
    elif args.limit:
        selected = list(enumerate(rows[: args.limit]))
    else:
        selected = list(enumerate(rows))

    print(f"Enriching {len(selected)} records (1 Apollo credit each)...")

    enriched_rows = []
    failed = []
    for idx, (orig_idx, row) in enumerate(selected):
        apollo_id = row[APOLLO_ID_COL] if len(row) > APOLLO_ID_COL else ""
        if not apollo_id:
            print(f"  [{idx + 1}/{len(selected)}] Row {orig_idx}: no apollo_id, skipping")
            failed.append(orig_idx)
            continue

        try:
            person = match_person(apollo_id, api_key)
            enriched_row = person_to_enriched_row(person)
            enriched_rows.append(enriched_row)
            name = person.get("name", row[0])
            linkedin = person.get("linkedin_url", "")
            print(f"  [{idx + 1}/{len(selected)}] {name} - LinkedIn: {'yes' if linkedin else 'no'}")
        except Exception as e:
            print(f"  [{idx + 1}/{len(selected)}] Row {orig_idx}: failed ({e})")
            failed.append(orig_idx)

        time.sleep(0.5)

    os.makedirs(os.path.dirname(args.output), exist_ok=True) if os.path.dirname(args.output) else None
    with open(args.output, "w") as f:
        json.dump({"mode": "people_enriched", "rows": enriched_rows}, f, indent=2)

    print(f"\nDone: {len(enriched_rows)} enriched, {len(failed)} failed → {args.output}")
    if failed:
        print(f"Failed row indices: {failed}")


if __name__ == "__main__":
    main()
