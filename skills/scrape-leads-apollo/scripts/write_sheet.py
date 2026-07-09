"""
Create a new Google Sheet and write Apollo lead data to it.

Uses the `gws` CLI (Google Workspace CLI) for all Sheets API calls.

Usage:
    python3 scripts/write_sheet.py .tmp/results.json --title "Leads - CEOs SaaS US"
"""
import argparse
import json
import subprocess
import sys

PEOPLE_HEADERS = [
    "full_name", "job_title", "company_name",
    "has_email", "has_phone", "apollo_id",
]

PEOPLE_ENRICHED_HEADERS = [
    "full_name", "job_title", "company_name", "company_domain",
    "location", "linkedin_url", "email", "email_status",
    "company_employees", "company_revenue",
]

COMPANIES_HEADERS = [
    "company_name", "domain", "industry", "location",
    "employees", "annual_revenue", "description",
]


def gws(*args, params: dict = None, body: dict = None) -> dict:
    cmd = ["gws", "sheets", "spreadsheets"] + list(args)
    if params:
        cmd += ["--params", json.dumps(params)]
    if body:
        cmd += ["--json", json.dumps(body)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gws error:\n{result.stdout}\n{result.stderr}")
    text = result.stdout.strip()
    return json.loads(text) if text else {}


def create_spreadsheet(title: str) -> str:
    result = gws("create", body={"properties": {"title": title}})
    return result["spreadsheetId"]


def write_data(sheet_id: str, tab: str, headers: list, rows: list) -> None:
    all_rows = [headers] + rows
    gws(
        "values", "append",
        params={
            "spreadsheetId": sheet_id,
            "range": f"{tab}!A1",
            "valueInputOption": "RAW",
            "insertDataOption": "INSERT_ROWS",
        },
        body={"values": all_rows},
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Path to results.json")
    parser.add_argument("--title", required=True, help="Google Sheet title")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    mode = data.get("mode", "people")
    rows = data.get("rows", [])
    if not rows:
        print("No rows to write.", file=sys.stderr)
        sys.exit(1)

    if mode == "people_enriched":
        headers = PEOPLE_ENRICHED_HEADERS
    elif mode == "companies":
        headers = COMPANIES_HEADERS
    else:
        headers = PEOPLE_HEADERS

    sheet_id = create_spreadsheet(args.title)
    write_data(sheet_id, "Sheet1", headers, rows)

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    print(url)


if __name__ == "__main__":
    main()
