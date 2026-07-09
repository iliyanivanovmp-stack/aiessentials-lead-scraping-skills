---
name: scrape-leads-apollo
description: Find people or companies from Apollo.io's 210M+ contact database via REST API and export to Google Sheet. Two modes: People (contacts by title, seniority, location, company size) and Companies (organizations by industry, headcount, revenue). Includes optional enrichment phase for LinkedIn, email, and full profile data (1 Apollo credit per contact). Use when asked to find leads on Apollo, search Apollo for contacts or companies, or scrape Apollo leads.
---

# Apollo Lead Finder

## Goal
Search Apollo.io's 210M+ contact database via REST API and export results to a Google Sheet. Two modes:
- **People** - find decision-maker contacts by title, seniority, location, company size, domains
- **Companies** - discover organizations by industry, location, headcount, revenue

Base directory after clone: `skills/scrape-leads-apollo`

## Available Filters

### People Filters

| Filter | Type | Notes |
|--------|------|-------|
| `person_titles` | string[] | Job title keywords, partial match (e.g. "CEO", "VP of Marketing") |
| `include_similar_titles` | bool | `true` = fuzzy match, `false` = strict |
| `person_seniorities` | enum[] | `owner`, `founder`, `c_suite`, `partner`, `vp`, `head`, `director`, `manager`, `senior`, `entry`, `intern` |
| `person_locations` | string[] | City, state, or country (e.g. "United States", "New York, New York") |
| `q_keywords` | string | Free-text keyword matched against full profile |
| `contact_email_status` | enum[] | `verified`, `unverified`, `likely to engage`, `unavailable` |
| `q_organization_domains_list` | string[] | Up to 1,000 company domains to scope search |
| `organization_locations` | string[] | Company HQ location |
| `organization_num_employees_ranges` | string[] | `"1,10"`, `"11,50"`, `"51,200"`, `"201,500"`, `"501,1000"`, `"1001,2000"`, `"2001,5000"`, `"5001,10000"`, `"10001,20000"` |
| `revenue_range` | object | `{"min": 1000000, "max": 50000000}` (integers, no symbols) |
| `currently_using_any_of_technology_uids` | string[] | Tech stack filters (e.g. "shopify", "hubspot") |

### Company Filters

| Filter | Type | Notes |
|--------|------|-------|
| `q_organization_name` | string | Company name (partial match) |
| `q_organization_keyword_tags` | string[] | Industry/keyword tags (e.g. "saas", "ecommerce", "fintech") |
| `organization_locations` | string[] | HQ city, state, or country |
| `organization_num_employees_ranges` | string[] | Same ranges as people filter |
| `revenue_range` | object | `{"min": ..., "max": ...}` |
| `latest_funding_amount_range` | object | `{"min": ..., "max": ...}` |
| `q_organization_job_titles` | string[] | Companies with active job postings for these roles |

## Step 1 - Determine Mode

If the user's request clearly implies a mode, proceed:
- "Find CMOs at DTC brands" → People
- "Find ecommerce companies in the UK with 50-500 employees" → Companies

Otherwise ask: "Are you looking for **people** (contacts) or **companies**?"

## Step 2 - Map Input to Filters

Map the user's natural language to the filter fields.

Example:
- "CEOs and Founders at SaaS companies in the US with 10-200 employees" →
  ```json
  {
    "person_titles": ["CEO", "Founder", "Co-Founder"],
    "person_seniorities": ["c_suite", "owner", "founder"],
    "q_organization_keyword_tags": ["saas"],
    "person_locations": ["United States"],
    "organization_num_employees_ranges": ["11,50", "51,200"]
  }
  ```

Confirm filter mapping in one short message:
```
Searching for:
  Mode: People
  Titles: CEO, Founder
  Seniority: c_suite, owner
  Industry: saas
  Location: United States
  Headcount: 11-200

Proceeding...
```

## Step 3 - Count First (Optional)

```bash
cd skills/scrape-leads-apollo
python3 scripts/search_apollo.py --mode people --count_only \
  --filters '{"person_titles": ["CEO"], "person_locations": ["United States"]}' \
  --output .tmp/results.json
```

Skip if the user has already specified a limit.

## Step 4 - Search with Pagination

```bash
cd skills/scrape-leads-apollo
python3 scripts/search_apollo.py --mode people \
  --filters '{"person_titles": ["CEO", "Founder"], "person_seniorities": ["c_suite", "owner"], "person_locations": ["United States"], "organization_num_employees_ranges": ["11,50", "51,200"]}' \
  --limit 200 \
  --output .tmp/results.json
```

For companies:
```bash
python3 scripts/search_apollo.py --mode companies \
  --filters '{"q_organization_keyword_tags": ["saas"], "organization_num_employees_ranges": ["11,50", "51,200"], "organization_locations": ["United States"]}' \
  --limit 100 \
  --output .tmp/results.json
```

Adjust `--limit` to what the user requested (default 200, cap at 500 for speed).

## Step 5 - Write to Google Sheet

```bash
cd skills/scrape-leads-apollo
python3 scripts/write_sheet.py .tmp/results.json --title "Leads - DESCRIPTION"
```

The script prints the sheet URL. **Share it with the user.**

### Search output columns (people)
`full_name | job_title | company_name | has_email | has_phone | apollo_id`

> Note: Apollo's search tier returns obfuscated last names and no emails/LinkedIn URLs. These are discovery signals. Enrichment (Step 6) reveals the full profile.

### Search output columns (companies)
`company_name | domain | industry | location | employees | annual_revenue | description`

---

## Step 6 - Ask About Enrichment (People Only)

After sharing the sheet URL, always ask:

> "Done - [N] leads saved to the sheet. Want me to enrich them?
>
> Enrichment reveals full names, LinkedIn profiles, emails, and location for each contact (1 Apollo credit per person). You can enrich all [N] or just a subset.
>
> Options:
> - **All [N] leads** - enrich everything
> - **Top [X]** - enrich the first X results
> - **Specific rows** - give me row numbers and I'll enrich only those
> - **Skip** - keep the discovery list as-is
>
> What would you like?"

Skip this step for company searches.

---

## Step 7 - Run Enrichment (If Requested)

Based on the user's answer, run the enrichment script:

```bash
# Enrich all
cd skills/scrape-leads-apollo
python3 scripts/enrich_apollo.py .tmp/results.json --output .tmp/enriched.json

# Enrich first 50
python3 scripts/enrich_apollo.py .tmp/results.json --output .tmp/enriched.json --limit 50

# Enrich specific rows (0-based index)
python3 scripts/enrich_apollo.py .tmp/results.json --output .tmp/enriched.json --rows 0,1,4,7
```

Then write enriched results to a new sheet:

```bash
python3 scripts/write_sheet.py .tmp/enriched.json --title "Leads Enriched - DESCRIPTION"
```

Share the new sheet URL with the user.

### Enriched output columns
`full_name | job_title | company_name | company_domain | location | linkedin_url | email | email_status | company_employees | company_revenue`

---

## Edge Cases

- **403 on search**: The script uses `/mixed_people/api_search`. If 403 persists, the API key may lack people search access.
- **0 results**: Broaden filters - fewer industry tags, wider location, more seniority values.
- **Rate limit (HTTP 429)**: Script sleeps 0.5s between pages. If 429 occurs during enrichment, wait 60 seconds and retry.
- **Domains search**: Apollo supports up to 1,000 domains per call. Chunk into multiple runs if more, then merge outputs.
- **Company searches**: Enrichment is not applicable. Companies mode shows full data in the search tier.
