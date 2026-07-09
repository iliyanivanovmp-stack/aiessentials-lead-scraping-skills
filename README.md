# The AIessentials Lead Scraping Skills Pack

Clone 4 working lead scraping skills: Google Maps, Lemlist, Apollo, and Instantly. Use them to build company lists, find decision makers, and export clean prospect sheets.

## What is inside

| Skill | Best for | Modes | Output |
| --- | --- | --- | --- |
| `gmaps-leads` | Local company discovery from Google Maps | Company source | Google Sheet with business name, address, phone, website, rating, review count, place ID |
| `scrape-leads-lemlist` | Company and people searches in Lemlist's lead database | Companies, People | Google Sheet with companies or contacts |
| `scrape-leads-apollo` | Apollo company and contact search, with optional paid enrichment | Companies, People, Enrichment | Google Sheet with discovery results or enriched contact data |
| `scrape-leads-instantly` | People search in Instantly SuperSearch | People | Google Sheet with contacts and company data |

## The 2 workflows

### Workflow 1: Company list first

Use this when you need businesses that match a category, location, size, or niche.

1. Run `gmaps-leads` for local businesses, or `scrape-leads-lemlist` / `scrape-leads-apollo` in company mode for database searches.
2. Export the company list to Google Sheets.
3. Deduplicate by domain, website, or `place_id`.
4. Use the company domains as input for the people workflow.

### Workflow 2: People list from known companies

Use this when you already know the accounts and need decision makers.

1. Start with company domains from Google Maps, Lemlist, Apollo, or your own CRM.
2. Run one of the people skills:
   - `scrape-leads-lemlist` for Lemlist contacts and emails.
   - `scrape-leads-apollo` for Apollo search, then enrich only the rows worth paying for.
   - `scrape-leads-instantly` for SuperSearch contact discovery.
3. Export to Google Sheets.
4. Review titles, seniority, domain match, and email availability before importing into outreach.

Google Maps itself is company-first. The people mode is the second step: take the websites or domains from the Google Maps sheet, then use a people database to find contacts at those companies.

## Install

Copy the skills into your local skills folder:

```bash
mkdir -p ~/.claude/skills
cp -R skills/* ~/.claude/skills/
```

For Codex-style local skills:

```bash
mkdir -p ~/.codex/skills
cp -R skills/* ~/.codex/skills/
```

Each skill has its own `SKILL.md` and `scripts/` folder.

## Setup

Create a `.env` file from the example:

```bash
cp .env.example .env
```

Then add the API keys you use:

```bash
GOOGLE_MAPS_API_KEY=
APOLLO_API_KEY=
INSTANTLY_API_KEY=
SERPAPI_KEY=
FIRECRAWL_API_KEY=
```

Google Sheets export needs OAuth credentials. Put `credentials.json` in the script folder for the skill that writes to Sheets. The first run will open Google OAuth and create `token.json` locally. Do not commit either file.

## Run examples

Google Maps company list:

```bash
cd skills/gmaps-leads/scripts
python3 gmaps_lead_pipeline.py --search "roofing companies in Austin Texas" --limit 40
```

Apollo people search:

```bash
cd skills/scrape-leads-apollo
python3 scripts/search_apollo.py --mode people \
  --filters '{"person_titles": ["Founder", "CEO"], "person_locations": ["United States"], "organization_num_employees_ranges": ["11,50", "51,200"]}' \
  --limit 100 \
  --output .tmp/results.json
python3 scripts/write_sheet.py .tmp/results.json --title "Leads - founders US"
```

Instantly people search:

```bash
cd skills/scrape-leads-instantly
python3 scripts/search_instantly.py \
  --filters '{"title": {"include": ["VP of Marketing"]}, "industry": {"include": ["Software & Internet"]}, "locations": [{"country": "United States"}]}' \
  --limit 100 \
  --output .tmp/results.json
python3 scripts/write_sheet.py .tmp/results.json --title "Leads - VP Marketing SaaS US"
```

Lemlist companies or people:

Use the Lemlist skill when your agent has the Lemlist connector available. The skill fetches live filter IDs first, then searches. Do not guess Lemlist filter IDs.

## What to use when

- Need local businesses by city or niche: start with `gmaps-leads`.
- Need companies in a broad B2B category: use Lemlist or Apollo company mode.
- Need verified contacts and are willing to spend enrichment credits: use Apollo search, then enrich only selected rows.
- Need a large people preview quickly: use Instantly.
- Need contacts at exact domains: use domain-scoped people search in Lemlist, Apollo, or Instantly.

## Safety notes

- This repo intentionally excludes `.env`, `.tmp`, `credentials.json`, `token.json`, and cache files.
- Respect each provider's terms and rate limits.
- Review and clean every list before sending outreach.

## Soft next step

If you want this running for your agency end-to-end, the 24/7 Pipeline Engine handles the whole system for you: https://aiessentials.us/24-7-pipeline-engine
