#!/usr/bin/env python3
"""
Smart Lead Finder

Automatically routes to the right data source based on the query:
  - Local businesses (HVAC, dentist, plumber…) → Google Maps Places API
  - Agencies / professional services (PPC, CRO, SEO…) → Clutch / DesignRush / organic

Usage:
    python3 gmaps_lead_pipeline.py --search "CRO agencies in United States" --limit 20
    python3 gmaps_lead_pipeline.py --search "HVAC companies in Austin TX" --limit 40
    python3 gmaps_lead_pipeline.py --search "SEO agencies in London" --limit 30 \\
        --sheet-url "https://docs.google.com/spreadsheets/d/..."
"""

import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import httpx
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from router import classify_query
from pipeline_agency import search_agencies, AGENCY_COLUMNS

# ── Unified column schema ─────────────────────────────────────────────────────
# Local fields:  address, phone, place_id
# Agency fields: min_project_size, team_size, source, location (city-level)
# Shared:        business_name, website, rating, review_count, search_query, scraped_at

SHEET_COLUMNS = [
    "business_name",
    "website",
    "address",          # local: full address | agency: ""
    "location",         # agency: city/country | local: ""
    "phone",            # local only
    "rating",
    "review_count",
    "min_project_size", # agency only
    "team_size",        # agency only
    "source",           # agency: clutch.co / designrush.com / organic | local: "google_maps"
    "place_id",         # local only
    "search_query",
    "scraped_at",
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.nationalPhoneNumber,places.websiteUri,places.rating,places.userRatingCount"
)


# ── Google Maps pipeline ──────────────────────────────────────────────────────

def search_places(query: str, max_results: int = 20) -> list[dict]:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Error: GOOGLE_MAPS_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": PLACES_FIELD_MASK,
        "Content-Type": "application/json",
    }

    results = []
    page_token = None

    while len(results) < max_results:
        body = {"textQuery": query, "maxResultCount": min(20, max_results - len(results))}
        if page_token:
            body["pageToken"] = page_token

        try:
            resp = httpx.post(PLACES_API_URL, headers=headers, json=body, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            print(f"Maps API error {e.response.status_code}: {e.response.text}", file=sys.stderr)
            break
        except Exception as e:
            print(f"Maps request failed: {e}", file=sys.stderr)
            break

        places = data.get("places", [])
        if not places:
            break

        now = datetime.now().isoformat()
        for p in places:
            results.append({
                "business_name": p.get("displayName", {}).get("text", ""),
                "website": p.get("websiteUri", ""),
                "address": p.get("formattedAddress", ""),
                "location": "",
                "phone": p.get("nationalPhoneNumber", ""),
                "rating": p.get("rating", ""),
                "review_count": p.get("userRatingCount", ""),
                "min_project_size": "",
                "team_size": "",
                "source": "google_maps",
                "place_id": p.get("id", ""),
                "search_query": query,
                "scraped_at": now,
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return results[:max_results]


# ── Google Sheets ─────────────────────────────────────────────────────────────

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


def save_to_sheet(leads: list[dict], sheet_url: str = None, sheet_name: str = None) -> str:
    creds = get_credentials()
    client = gspread.authorize(creds)

    if sheet_url:
        sheet_id = sheet_url.split("/d/")[1].split("/")[0]
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.sheet1
        print(f"Opened existing sheet: {spreadsheet.title}")

        # Deduplicate by place_id (local) or website (agency)
        place_id_col = SHEET_COLUMNS.index("place_id") + 1
        website_col = SHEET_COLUMNS.index("website") + 1
        existing_place_ids = set(worksheet.col_values(place_id_col)[1:])
        existing_websites = set(worksheet.col_values(website_col)[1:])

        new_leads = []
        for l in leads:
            pid = l.get("place_id", "")
            web = l.get("website", "")
            if (pid and pid in existing_place_ids) or (web and web in existing_websites):
                continue
            new_leads.append(l)

        skipped = len(leads) - len(new_leads)
    else:
        name = sheet_name or "Leads"
        spreadsheet = client.create(name)
        worksheet = spreadsheet.sheet1
        worksheet.update(values=[SHEET_COLUMNS], range_name="A1")
        worksheet.format(f"A1:{chr(64 + len(SHEET_COLUMNS))}1", {"textFormat": {"bold": True}})
        worksheet.freeze(rows=1)
        print(f"Created new sheet: {name}")
        print(f"Sheet URL: {spreadsheet.url}")
        new_leads = leads
        skipped = 0

    if not new_leads:
        print("No new leads to add (all duplicates).")
        return spreadsheet.url

    rows = [[lead.get(col, "") for col in SHEET_COLUMNS] for lead in new_leads]
    worksheet.append_rows(rows, value_input_option="RAW")
    print(f"Added {len(new_leads)} leads" + (f" ({skipped} duplicates skipped)" if skipped else ""))
    return spreadsheet.url


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Smart lead finder: Google Maps for local, Clutch/DesignRush for agencies")
    parser.add_argument("--search", required=True, help='Search query (e.g., "CRO agencies in US")')
    parser.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    parser.add_argument("--sheet-url", help="Existing Google Sheet URL to append to")
    parser.add_argument("--sheet-name", help="Name for new sheet")
    parser.add_argument("--source", choices=["auto", "maps", "agency"], default="auto",
                        help="Force a pipeline (default: auto-detect)")
    args = parser.parse_args()

    # Route
    if args.source == "auto":
        route = classify_query(args.search)
    else:
        route = "local" if args.source == "maps" else "agency"

    print(f"Query: '{args.search}'")
    print(f"Route: {route.upper()} pipeline")
    print()

    if route == "local":
        leads = search_places(args.search, max_results=args.limit)
    else:
        leads = search_agencies(args.search, limit=args.limit)

    if not leads:
        print("No results found.")
        sys.exit(1)

    print(f"\nFound {len(leads)} leads. Saving to sheet...")
    sheet_url = save_to_sheet(leads, sheet_url=args.sheet_url, sheet_name=args.sheet_name)
    print(f"Done. Sheet: {sheet_url}")


if __name__ == "__main__":
    main()
