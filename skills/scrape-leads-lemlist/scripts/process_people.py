"""
Merge, deduplicate, and rank lemleads_search results for People mode.

Input:  .tmp/raw_results.json  - {"pages": [{page response}, ...]}
Output: .tmp/processed.json   - list of sheet-ready row arrays

Usage:
    python3 scripts/process_people.py .tmp/raw_results.json --output .tmp/processed.json
"""
import argparse
import json
import re
import sys


# ---------------------------------------------------------------------------
# Decision-maker title classification
# ---------------------------------------------------------------------------

DECISION_MAKER_TITLES = [
    "vp", "vice president", "v.p.",
    "director",
    "founder", "co-founder", "cofounder",
    "owner",
    "president",
    "ceo", "coo", "cmo", "cso", "cro", "cpo",
    "chief",
    "head of",
]

EXCLUDED_TITLE_KEYWORDS = [
    "retired",
    "board of director",
    "board member",
    "board advisor",
    "franchisee",
    "franchise owner",
    "franchise",
    "self employed",
    "self-employed",
]

SHORT_ACRONYM_PATTERN = re.compile(r"\b(?:ceo|coo|cmo|cro|vp)\b")


def title_is_decision_maker(title: str) -> bool:
    t = title.lower()
    if SHORT_ACRONYM_PATTERN.search(t):
        return True
    return any(kw in t for kw in DECISION_MAKER_TITLES
               if kw not in {"ceo", "coo", "cmo", "cro", "vp"})


def title_is_excluded(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in EXCLUDED_TITLE_KEYWORDS)


def title_priority(title: str) -> int:
    t = title.lower()
    is_vp = bool(re.search(r"\bvp\b", t)) or any(k in t for k in ["vice president", "svp", "evp"])
    has_ceo = bool(re.search(r"\bceo\b", t))
    has_cmo = bool(re.search(r"\bcmo\b", t))
    has_cro = bool(re.search(r"\bcro\b", t))
    has_coo = bool(re.search(r"\bcoo\b", t))
    ecom_relevant = any(k in t for k in [
        "ecommerce", "e-commerce", "digital", "marketing",
        "revenue", "growth", "commercial", "sales", "crm",
    ])

    if any(k in t for k in ["founder", "co-founder", "cofounder"]) or has_ceo:
        return 0
    if "president" in t and not is_vp:
        return 0
    if ecom_relevant:
        if "chief" in t or has_cmo or has_cro or any(k in t for k in ["cco", "cgo", "cdo"]):
            return 1
        if is_vp:
            return 1
    if ecom_relevant and any(k in t for k in ["director", "head of"]):
        return 2
    if "owner" in t:
        return 3
    if any(k in t for k in ["chief", "cto", "cpo", "cso", "cdo", "cco", "cgo", "svp", "evp"]):
        return 4
    if has_cmo or has_cro or has_coo:
        return 4
    if is_vp:
        return 5
    if any(k in t for k in ["director", "head of"]):
        return 6
    return 7


# ---------------------------------------------------------------------------
# Lead parsing
# ---------------------------------------------------------------------------

def current_exp(lead: dict) -> dict:
    exps = lead.get("experiences", [])
    return next((e for e in exps if e.get("order_in_profile") == 1), {})


def lead_identity_key(lead: dict) -> str:
    linkedin_url = (lead.get("lead_linkedin_url", "") or "").strip().lower()
    if linkedin_url:
        return f"linkedin:{linkedin_url}"
    public_profile_id = lead.get("public_profile_id")
    if public_profile_id:
        return f"public:{public_profile_id}"
    lead_id = lead.get("lead_id")
    if lead_id:
        return f"id:{lead_id}"
    parent_id = lead.get("parent_id")
    if parent_id:
        return f"parent:{parent_id}"
    exp = current_exp(lead)
    fallback = "|".join([
        (lead.get("full_name", "") or "").strip().lower(),
        (lead.get("potential_email", "") or "").strip().lower(),
        (exp.get("company_domain", "") or "").strip().lower(),
        (exp.get("title", "") or "").strip().lower(),
    ])
    return f"fallback:{fallback}"


def dedupe(leads: list) -> list:
    seen = set()
    out = []
    for lead in leads:
        key = lead_identity_key(lead)
        if key not in seen:
            seen.add(key)
            out.append(lead)
    return out


def sort_key(lead: dict) -> tuple:
    title = current_exp(lead).get("title", "")
    return (title_priority(title), 0 if lead.get("potential_email") else 1)


def lead_to_row(lead: dict) -> list:
    exp = current_exp(lead)
    company_domain = exp.get("company_domain", "")
    company_name = exp.get("company_name", lead.get("company_name", ""))
    return [
        company_domain,
        company_name,
        lead.get("full_name", ""),
        lead.get("potential_email", ""),
        lead.get("lead_linkedin_url", ""),
        exp.get("title", ""),
        lead.get("seniority", ""),
        lead.get("department", ""),
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def normalize_domain(d: str) -> str:
    """Strip www. and common subdomains for comparison."""
    d = (d or "").lower().strip().rstrip("/")
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    return d


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Path to raw_results.json")
    parser.add_argument("--output", required=True, help="Path to write processed JSON")
    parser.add_argument("--domains", help="Path to JSON file with list of searched domains (used to filter out fuzzy-matched contacts from unrelated companies)")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    # Support both {"pages": [...]} and a flat list of leads
    if isinstance(data, dict) and "pages" in data:
        all_leads = []
        for page in data["pages"]:
            all_leads.extend(page.get("results", []))
    elif isinstance(data, list):
        all_leads = data
    else:
        print(f"Unexpected input format", file=sys.stderr)
        sys.exit(1)

    # Filter to only contacts whose current company domain is in the searched list
    allowed_domains = None
    if args.domains:
        with open(args.domains) as f:
            raw = json.load(f)
        allowed_domains = {normalize_domain(d) for d in raw if d}

    if allowed_domains:
        before = len(all_leads)
        all_leads = [
            lead for lead in all_leads
            if normalize_domain(current_exp(lead).get("company_domain", "")) in allowed_domains
        ]
        print(f"Domain filter: {before} → {len(all_leads)} leads (removed {before - len(all_leads)} from unrelated companies)")

    unique_leads = dedupe(all_leads)

    # Split into decision-makers and others, rank both groups
    decision_makers = [l for l in unique_leads
                       if not title_is_excluded(current_exp(l).get("title", ""))
                       and title_is_decision_maker(current_exp(l).get("title", ""))]
    others = [l for l in unique_leads
              if not title_is_excluded(current_exp(l).get("title", ""))
              and not title_is_decision_maker(current_exp(l).get("title", ""))]

    decision_makers.sort(key=sort_key)
    others.sort(key=sort_key)

    ranked = decision_makers + others
    rows = [lead_to_row(lead) for lead in ranked]

    with open(args.output, "w") as f:
        json.dump({"mode": "people", "rows": rows}, f, indent=2)

    print(f"People: {len(rows)} unique contacts ({len(decision_makers)} decision-makers, {len(others)} others)")


if __name__ == "__main__":
    main()
