---
name: gmaps-leads
description: Find local businesses on Google Maps and save them to a Google Sheet. Use when user asks to find local businesses, scrape Google Maps, or build a lead list from Google Maps results.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Google Maps Lead Finder

## Goal
Search Google Maps for businesses matching a query and output a Google Sheet with company name, address, phone, website, rating, and review count.

## Inputs
| Parameter | Required | Description |
|-----------|----------|-------------|
| `--search` | Yes | Search query (e.g., "PPC companies in Vancouver, Canada") |
| `--limit` | No | Max results (default: 20, max ~60 via pagination) |
| `--sheet-url` | No | Existing sheet to append to (deduplicates by place_id) |
| `--sheet-name` | No | Name for new sheet |

## Usage
```bash
cd skills/gmaps-leads/scripts

# New sheet
python3 gmaps_lead_pipeline.py --search "PPC companies in Vancouver, Canada" --limit 20

# Append to existing sheet
python3 gmaps_lead_pipeline.py --search "SEO agencies in Toronto" --limit 30 \
  --sheet-url "https://docs.google.com/spreadsheets/d/..."
```

## Output Columns
`business_name`, `address`, `phone`, `website`, `rating`, `review_count`, `place_id`, `search_query`, `scraped_at`

## Environment
```
GOOGLE_MAPS_API_KEY=your_key   # in .env
```
Google Sheets auth: `credentials.json` + `token.json` (OAuth 2.0, configured on first run).

## Notes
- Uses Google Maps Places API (New) - Text Search endpoint
- Deduplicates by `place_id` when appending to an existing sheet
- Max 20 results per API call; paginates automatically up to `--limit`
- Auth: first run opens a browser for Google OAuth consent
