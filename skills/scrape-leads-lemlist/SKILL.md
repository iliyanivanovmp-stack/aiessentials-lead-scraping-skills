---
name: scrape-leads-lemlist
description: Find companies or decision-maker contacts from the lemlist lead database. Two modes: Companies (discover businesses by industry/location/size) or People (find contacts by seniority/title/company domains). Outputs to Google Sheet. Use when user asks to find leads, build prospect lists, or search the lemlist database.
allowed-tools: Bash, Read, Write, Edit, mcp__claude_ai_lemlist__get_lemleads_filters, mcp__claude_ai_lemlist__lemleads_search
---

# Lemlist Lead Finder

## Goal
Search the lemlist database and export results to a Google Sheet. Two modes:
- **Companies** - discover businesses matching industry, location, headcount, revenue criteria
- **People** - find decision-maker contacts, optionally scoped to specific company domains

## Step 1 - Determine Mode

If the user's request clearly implies a mode, proceed without asking:
- "Find SaaS companies in Canada" → Companies
- "Find CMOs at ecommerce brands" → People

Otherwise ask: "Are you looking for **companies** or **people** (contacts)?"

## Step 2 - Fetch Available Filters

Call `get_lemleads_filters` to get the live filter catalog. The mode parameter maps as:
- Companies mode → call with mode "companies" (or check catalog for company-specific filters)
- People mode → call with mode "leads"

Parse the response. Extract:
- `filterId` - the key to use in the search payload
- `type` - "text", "select", "range", etc.
- `values` - allowed values for select filters
- `mode` - which modes the filter is available in

Never guess filter IDs. Only use what the catalog returns.

## Step 3 - Map User Input to Filters

Take the user's natural language description and map to the available filter IDs. Examples:

| User says | Maps to |
|-----------|---------|
| "US" / "United States" | location or country filter |
| "1-50 employees" | headcount range filter |
| "SaaS" / "software" | industry or keyword filter |
| "CEO, Founder, CMO" | job title filter |
| "executive" | seniority: "Executive Leadership", "Ownership / Firm Leadership" |
| "marketing director" | seniority: "Department Leadership" + title keyword |
| "these domains: a.com, b.com" | currentCompanyWebsiteUrl filter |

Confirm your filter mapping in one short message before searching:
```
Searching for:
  Mode: People
  Seniority: Executive Leadership, Ownership / Firm Leadership
  Industry: SaaS / Software
  Location: United States
  Count target: 200

Proceeding...
```

If a filter the user mentioned doesn't exist in the catalog, note it and proceed with what's available.

## Step 4 - Search with Pagination

Build the search payload:
```json
{
  "mode": "people",
  "page": 1,
  "size": 100,
  "filters": [
    { "filterId": "FILTER_ID", "in": ["VALUE1", "VALUE2"], "out": [] }
  ]
}
```

Call `lemleads_search` and save each page response to `.tmp/page_{N}.json`.

Keep paginating (increment page) until:
- `hasMore` is `false`, OR
- You've collected the user's requested count (default: collect all available, cap at 500)

After all pages, write a merged file `.tmp/raw_results.json` - a JSON object with a `"pages"` array containing all page responses:
```json
{ "pages": [ {page1 response}, {page2 response}, ... ] }
```

**If the search used `currentCompanyWebsiteUrl` domains**, also save the full list of searched domains to `.tmp/searched_domains.json` (a flat JSON array of domain strings). This is required for the domain filter in Step 5 to remove fuzzy-matched contacts from unrelated companies.

## Step 5 - Process Results

### People mode
```bash
cd skills/scrape-leads-lemlist
python3 scripts/process_people.py .tmp/raw_results.json --output .tmp/processed.json
```

**When `currentCompanyWebsiteUrl` domains were used**, always pass `--domains` to strip out contacts the API fuzzy-matched from unrelated companies:
```bash
python3 scripts/process_people.py .tmp/raw_results.json --output .tmp/processed.json --domains .tmp/searched_domains.json
```

Deduplicates and ranks by decision-maker score. Prints count of unique contacts found.

### Companies mode
```bash
cd skills/scrape-leads-lemlist
python3 scripts/process_companies.py .tmp/raw_results.json --output .tmp/processed.json
```
Deduplicates and formats company records. Prints count found.

## Step 6 - Write to Google Sheet

```bash
cd skills/scrape-leads-lemlist
python3 scripts/write_sheet.py .tmp/processed.json --mode people --title "Leads - DESCRIPTION"
```

Replace DESCRIPTION with a short label from the user's search (e.g., "CMOs SaaS US", "VPC Agencies CA").

The script creates a new Google Sheet, writes the data, and prints the sheet URL.

**The sheet URL is the only deliverable.** Share it with the user.

## Output Columns

### People
`company_domain | company_name | full_name | email | linkedin_url | job_title | seniority | department`

### Companies
`company_name | domain | industry | location | headcount | annual_revenue | website | description`

## Edge Cases

- **No results**: Suggest broadening filters (less specific industry, wider location, more seniority values).
- **Filter not in catalog**: Skip it, tell the user which filter was dropped.
- **Pagination stalls or returns errors**: Retry that page once. If it fails again, process whatever was collected and note truncation.
- **People mode with company domains**: If the user provides specific company domains, add them to `currentCompanyWebsiteUrl.in`. Pool up to 50 domains per search call; chunk into multiple calls if more. Always save the full domain list to `.tmp/searched_domains.json` and pass `--domains .tmp/searched_domains.json` to `process_people.py` - the Lemlist API does fuzzy/partial domain matching and will return contacts from unrelated companies (e.g., searching `hilo.com` can return people at `studio-hilo.com`). The `--domains` flag filters these out.
