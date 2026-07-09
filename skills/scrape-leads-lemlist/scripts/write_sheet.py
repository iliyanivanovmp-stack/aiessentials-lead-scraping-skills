"""
Create a new Google Sheet and write processed lead data to it.

Uses the `gws` CLI (Google Workspace CLI) for all Sheets API calls.

Usage:
    python3 scripts/write_sheet.py .tmp/processed.json --mode people --title "Leads - CMOs US"
    python3 scripts/write_sheet.py .tmp/processed.json --mode companies --title "Companies - SaaS CA"
"""
import argparse
import json
import subprocess
import sys

PEOPLE_HEADERS = [
    "company_domain", "company_name", "full_name", "email",
    "linkedin_url", "job_title", "seniority", "department",
]

COMPANIES_HEADERS = [
    "company_name", "domain", "industry", "location",
    "headcount", "annual_revenue", "website", "description",
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
    parser.add_argument("input", help="Path to processed.json")
    parser.add_argument("--mode", required=True, choices=["people", "companies"])
    parser.add_argument("--title", required=True, help="Google Sheet title")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    rows = data.get("rows", [])
    if not rows:
        print("No rows to write.", file=sys.stderr)
        sys.exit(1)

    headers = PEOPLE_HEADERS if args.mode == "people" else COMPANIES_HEADERS

    sheet_id = create_spreadsheet(args.title)
    write_data(sheet_id, "Sheet1", headers, rows)

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    print(url)


if __name__ == "__main__":
    main()
