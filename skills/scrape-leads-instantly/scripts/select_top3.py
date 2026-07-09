"""
From the full lead pool, pick the best 3 per company.
Priority: founders/CEOs > C-suite > heads/directors/VPs > functional managers.
"""
import json
import re
import sys

PRIORITY_PATTERNS = [
    # Tier 1 - Founders / Owners / CEO
    (1, r'\b(founder|co-founder|co founder|owner|proprietor|ceo|chief executive|president|managing director|md)\b'),
    # Tier 2 - Other C-suite
    (2, r'\b(coo|cfo|cto|cmo|cpo|cro|cso|chief operating|chief financial|chief technology|chief marketing|chief product|chief revenue|chief growth)\b'),
    # Tier 3 - Heads / VPs / Directors
    (3, r'\b(vice president|vp |svp|evp|director|head of|team lead|lead)\b'),
    # Tier 4 - Operational / growth / revenue managers
    (4, r'\b((operations|ops|growth|revenue|sales|marketing|business development|affiliate|partnerships).{0,20}manager|manager.{0,20}(operations|ops|growth|revenue|sales|marketing|business development|affiliate|partnerships))\b'),
    # Tier 5 - Other managers
    (5, r'\b(manager)\b'),
]


def score(title: str) -> int:
    t = title.lower()
    for tier, pattern in PRIORITY_PATTERNS:
        if re.search(pattern, t):
            return tier
    return 99


def seniority_penalty(title: str) -> int:
    t = title.lower()
    if re.search(r'\b(junior|assistant|support|specialist|designer|developer|engineer|qa)\b', t):
        return 1
    return 0


def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else ".tmp/all_results.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else ".tmp/top3_results.json"

    with open(input_file) as f:
        data = json.load(f)

    rows = data["rows"]

    # Group by source_domain (col 5)
    by_company: dict[str, list] = {}
    for row in rows:
        domain = row[5] if len(row) > 5 else "unknown"
        by_company.setdefault(domain, []).append(row)

    selected = []
    coverage = {}

    for domain, leads in by_company.items():
        # Sort by decision-maker priority, then avoid junior/support/IC roles.
        ranked = sorted(leads, key=lambda r: (score(r[1]), seniority_penalty(r[1]), -len(r[1])))
        top3 = ranked[:3]
        selected.extend(top3)
        coverage[domain] = len(top3)

    # Stats
    total_companies = len(by_company)
    full = sum(1 for v in coverage.values() if v >= 3)
    partial = sum(1 for v in coverage.values() if 1 <= v < 3)
    zero = sum(1 for v in coverage.values() if v == 0)

    print(f"Companies in pool: {total_companies}")
    print(f"  Full (3 leads):    {full}")
    print(f"  Partial (1-2):     {partial}")
    print(f"  Zero:              {zero}")
    print(f"Total leads selected: {len(selected)}")

    # Show role distribution
    tier_counts = {}
    for row in selected:
        t = score(row[1])
        tier_counts[t] = tier_counts.get(t, 0) + 1
    tier_labels = {
        1: "Founder/CEO/Owner",
        2: "Other C-suite",
        3: "Head/VP/Director",
        4: "Functional manager",
        5: "Other manager",
        99: "Other",
    }
    print("\nRole distribution:")
    for tier in sorted(tier_counts):
        print(f"  {tier_labels.get(tier, tier)}: {tier_counts[tier]}")

    with open(output_file, "w") as f:
        json.dump({"mode": "people", "rows": selected}, f, indent=2)

    print(f"\nSaved to {output_file}")


if __name__ == "__main__":
    main()
