#!/usr/bin/env python3
"""
Multi-query Google Maps scraper.

Runs a list of search queries sequentially and appends all results to the same
Google Sheet, deduplicating by place_id.

Usage:
    python3 gmaps_multi_query.py --queries queries.txt --sheet-name "CRO Agencies US"
    python3 gmaps_multi_query.py --queries queries.txt --sheet-url "https://..."
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

# Add scripts dir to path so we can import the main pipeline module
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
import httpx
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

load_dotenv(Path(__file__).parent.parent / ".env")

PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = "places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.websiteUri,places.rating,places.userRatingCount"

SHEET_COLUMNS = [
    "business_name", "address", "phone", "website",
    "rating", "review_count", "place_id", "search_query", "scraped_at",
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def search_places(query: str, max_results: int = 60) -> list[dict]:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Error: GOOGLE_MAPS_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
        "Content-Type": "application/json",
    }

    results = []
    page_token = None

    while len(results) < max_results:
        body = {
            "textQuery": query,
            "maxResultCount": min(20, max_results - len(results)),
        }
        if page_token:
            body["pageToken"] = page_token

        try:
            response = httpx.post(PLACES_API_URL, headers=headers, json=body, timeout=15.0)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            print(f"  API error {e.response.status_code}: {e.response.text}", file=sys.stderr)
            break
        except Exception as e:
            print(f"  Request failed: {e}", file=sys.stderr)
            break

        places = data.get("places", [])
        if not places:
            break

        now = datetime.now().isoformat()
        for place in places:
            results.append({
                "business_name": place.get("displayName", {}).get("text", ""),
                "address": place.get("formattedAddress", ""),
                "phone": place.get("nationalPhoneNumber", ""),
                "website": place.get("websiteUri", ""),
                "rating": place.get("rating", ""),
                "review_count": place.get("userRatingCount", ""),
                "place_id": place.get("id", ""),
                "search_query": query,
                "scraped_at": now,
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return results[:max_results]


def get_credentials():
    token_path = Path(__file__).parent / "token.json"
    creds_path = Path(__file__).parent / "credentials.json"
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    if not creds or not creds.valid:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return creds


def main():
    parser = argparse.ArgumentParser(description="Multi-query Google Maps scraper")
    parser.add_argument("--queries", help="Text file with one search query per line")
    parser.add_argument("--sheet-url", help="Existing Google Sheet URL to append to")
    parser.add_argument("--sheet-name", default="GMaps Leads", help="Name for new sheet")
    parser.add_argument("--per-query-limit", type=int, default=60, help="Max results per query (default: 60)")
    args = parser.parse_args()

    if args.queries:
        queries = [q.strip() for q in Path(args.queries).read_text().splitlines() if q.strip()]
    else:
        print("Error: --queries file required", file=sys.stderr)
        sys.exit(1)

    print(f"Running {len(queries)} queries...\n")

    creds = get_credentials()
    client = gspread.authorize(creds)

    # Create or open sheet
    if args.sheet_url:
        sheet_id = args.sheet_url.split("/d/")[1].split("/")[0]
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.sheet1
        print(f"Opened existing sheet: {spreadsheet.title}")
    else:
        spreadsheet = client.create(args.sheet_name)
        worksheet = spreadsheet.sheet1
        worksheet.update(values=[SHEET_COLUMNS], range_name="A1")
        worksheet.format("A1:I1", {"textFormat": {"bold": True}})
        worksheet.freeze(rows=1)
        print(f"Created new sheet: {args.sheet_name}")
        print(f"Sheet URL: {spreadsheet.url}\n")

    total_added = 0
    total_skipped = 0
    place_id_col = SHEET_COLUMNS.index("place_id") + 1

    for i, query in enumerate(queries, 1):
        print(f"[{i}/{len(queries)}] Searching: '{query}'")
        leads = search_places(query, max_results=args.per_query_limit)

        if not leads:
            print(f"  No results.")
            continue

        # Fetch current known IDs (refresh each time to avoid cross-query dupes)
        existing_ids = set(worksheet.col_values(place_id_col)[1:])
        new_leads = [l for l in leads if l["place_id"] not in existing_ids]
        skipped = len(leads) - len(new_leads)

        if new_leads:
            rows = [[lead.get(col, "") for col in SHEET_COLUMNS] for lead in new_leads]
            worksheet.append_rows(rows, value_input_option="RAW")
            total_added += len(new_leads)

        total_skipped += skipped
        print(f"  +{len(new_leads)} new  ({skipped} dupes skipped)  | total so far: {total_added}")

    print(f"\nDone. {total_added} unique leads added ({total_skipped} duplicates skipped).")
    print(f"Sheet: {spreadsheet.url}")


if __name__ == "__main__":
    main()
