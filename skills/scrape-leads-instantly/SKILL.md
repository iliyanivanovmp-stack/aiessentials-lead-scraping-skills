---
name: scrape-leads-instantly
description: Find decision-maker contacts from the Instantly SuperSearch database. Filters by job title, seniority level, department, industry, location, company size, revenue, and more. Outputs to Google Sheet. Use when user asks to find leads, build prospect lists, or search the Instantly lead database.
allowed-tools: Bash, Read, Write, Edit
---

# Instantly Lead Finder

## Goal
Search the Instantly SuperSearch lead database via REST API and export results to a Google Sheet.

> Note: Instantly's SuperSearch is not exposed via MCP - this skill uses the REST API directly through Python. The Instantly MCP (available for campaigns/inboxes) is a separate tool.

## Available Filters

Map user input to these `search_filters` fields:

| Filter | Type | Accepted values |
|--------|------|-----------------|
| `title.include` | string[] | Free text job titles (e.g. "CEO", "VP of Marketing") |
| `title.exclude` | string[] | Titles to exclude |
| `level` | enum[] | "Owner", "Chief X Officer (CxO)", "Vice President (VP)", "Executive", "Director", "Manager", "Senior", "Mid-Senior level", "Associate", "Partner", "Entry level", "Internship", "Unpaid / Internship" |
| `department` | enum[] | "Engineering", "Finance & Administration", "Human Resources", "IT & IS", "Marketing", "Operations", "Sales", "Support", "Other" |
| `industry.include` | enum[] | "Agriculture & Mining", "Business Services", "Computers & Electronics", "Consumer Services", "Education", "Energy & Utilities", "Financial Services", "Government", "Healthcare, Pharmaceuticals, & Biotech", "Manufacturing", "Media & Entertainment", "Non-Profit", "Other", "Real Estate & Construction", "Retail", "Software & Internet", "Telecommunications", "Transportation & Storage", "Travel, Recreation, and Leisure", "Wholesale & Distribution" |
| `industry.exclude` | enum[] | Same values as include |
| `locations` | object[] | `[{"country": "United States"}]` or `[{"city": "New York", "state": "New York", "country": "United States"}]` |
| `employeeCount` | mixed[] | Preset: "0 - 25", "25 - 100", "100 - 250", "250 - 1000", "1K - 10K", "10K - 50K", "50K - 100K", "> 100K". Custom: `{"op": "between", "min": 10, "max": 200}` |
| `revenue` | enum[] | "$0 - 1M", "$1 - 10M", "$10 - 50M", "$50 - 100M", "$100 - 250M", "$250 - 500M", "$500M - 1B", "> $1B" |
| `company_name.include` | string[] | Company names to target |
| `company_name.exclude` | string[] | Company names to exclude |
| `domains` | string[] | Exact company domains to target (e.g. `["convertibles.dev"]`). Use this for known-company contact generation. |
| `keyword_filter.include` | string | Keyword to match in profile/company description |
| `keyword_filter.exclude` | string | Keyword to exclude |
| `look_alike` | string | Domain of a company to find similar companies (e.g. "stripe.com"). Do not use this for exact company targeting. |
| `news` | enum[] | Company news signals: "launches", "receives_financing", "hires", "partners_with", "acquires", "goes_public", etc. |
| `name` | string[] | Specific person names to search |

## Step 1 - Map Input to Filters

Take the user's natural language description and map it to the filter fields above. Examples:

- "CEOs and Founders at SaaS companies in the US with 10-200 employees" →
  ```json
  {
    "title": {"include": ["CEO", "Founder", "Co-Founder"]},
    "industry": {"include": ["Software & Internet"]},
    "locations": [{"country": "United States"}],
    "employeeCount": [{"op": "between", "min": 10, "max": 200}]
  }
  ```

- "VPs of Marketing at ecommerce brands with $1M-$50M revenue" →
  ```json
  {
    "title": {"include": ["VP of Marketing", "Vice President of Marketing"]},
    "industry": {"include": ["Retail", "Consumer Services"]},
    "revenue": ["$1 - 10M", "$10 - 50M"]
  }
  ```

- "Find decision makers at convertibles.dev" →
  ```json
  {
    "domains": ["convertibles.dev"]
  }
  ```

  For exact domain searches, start with `domains` only and rank/filter locally.
  Adding narrow `title` or `level` filters can hide useful people whose titles
  are blank, non-standard, or not mapped cleanly by Instantly.

Confirm the filter mapping in one short message before searching:
```
Searching for:
  Titles: CEO, Founder
  Level: Chief X Officer (CxO), Owner
  Industry: Software & Internet
  Location: United States
  Headcount: 10-200

Proceeding...
```

If the user mentioned something not in the filter list (e.g. "startup stage"), note it and proceed with what's available.

## Step 2 - Count First (Optional)

Before fetching, run a count to set expectations:
```bash
cd skills/scrape-leads-instantly
python3 scripts/search_instantly.py --count_only \
  --filters '{"title": {"include": ["CEO"]}, "locations": [{"country": "United States"}]}' \
  --output .tmp/results.json
```

This prints the total lead count without fetching. Skip if the user already specified a limit.

## Step 3 - Search with Pagination

```bash
cd skills/scrape-leads-instantly
python3 scripts/search_instantly.py \
  --filters '{"title": {"include": ["CEO"]}, "level": ["Chief X Officer (CxO)", "Owner", "Executive"], "locations": [{"country": "United States"}], "industry": {"include": ["Software & Internet"]}, "employeeCount": ["0 - 25", "25 - 100"]}' \
  --limit 200 \
  --output .tmp/results.json
```

The script paginates automatically (25 results per page) until the limit is reached or no more results.

Adjust `--limit` to what the user requested (default 200, max 500 per run to avoid long waits).

## Step 4 - Write to Google Sheet

```bash
cd skills/scrape-leads-instantly
python3 scripts/write_sheet.py .tmp/results.json --title "Leads - DESCRIPTION"
```

Replace DESCRIPTION with a short label (e.g. "CEOs SaaS US", "CMOs Ecommerce").

The script creates a new Google Sheet, writes the data, and prints the URL.

**The sheet URL is the only deliverable.** Share it with the user.

## Output Columns

`full_name | job_title | company_name | location | linkedin_url | company_domain | company_id`

> Instantly's preview API does not return emails. If emails are needed, the user must use the Instantly app's "Enrich" feature, which imports leads into a campaign/list and finds emails (costs enrichment credits).

## Edge Cases

- **Known company domain searches**: Use `domains`, not `look_alike`, `domain`, `company_domain`, or `website`. `look_alike` returns similar companies, not exact contacts at the target domain. The API ignores or misinterprets unsupported domain-like keys.
- **Filter validation error**: The error message will name the invalid field. Adjust the value to match the allowed enum.
- **0 results**: Broaden filters - remove industry or expand location.
- **Large datasets (1M+ matches)**: Always set a practical `--limit`. The database is massive; cap at 500 for quick runs.
- **Rate limits**: Script retries once automatically. If it fails again, reduce `--limit` and run again.
