"""
Query router: classifies a search query as 'local' or 'agency'.

Local  = brick-and-mortar businesses found on Google Maps (HVAC, dentist, etc.)
Agency = B2B professional services (PPC, CRO, SEO agencies, consultants, etc.)
"""

AGENCY_KEYWORDS = {
    # Business types
    "agency", "agencies", "firm", "firms", "studio", "studios",
    "consultant", "consultants", "consulting",
    # Digital marketing services
    "ppc", "seo", "cro", "sem", "smm", "saas",
    "digital marketing", "content marketing", "email marketing",
    "social media marketing", "affiliate marketing",
    "conversion rate optimization", "conversion optimization",
    "web design", "web development", "web agency",
    "branding", "advertising", "public relations",
    "ux design", "ui design", "product design",
    "ecommerce agency", "shopify agency", "magento",
    "software development", "app development", "mobile app development",
    "data analytics", "business intelligence",
    "staffing agency", "recruiting agency", "hr consulting",
    "management consulting", "strategy consulting",
    "financial advisory", "accounting firm", "law firm",
    "it services", "managed services", "it consulting",
    "link building", "outreach agency", "pr firm",
    "video production agency", "creative agency",
    "growth agency", "demand generation",
}

LOCAL_KEYWORDS = {
    "hvac", "plumber", "plumbing", "electrician", "contractor",
    "dentist", "dental", "doctor", "clinic", "hospital", "pharmacy",
    "restaurant", "cafe", "coffee shop", "bakery", "food",
    "gym", "fitness", "yoga", "pilates",
    "salon", "barber", "spa", "nail salon",
    "auto repair", "mechanic", "car wash", "dealership",
    "florist", "grocery", "supermarket", "store",
    "hotel", "motel", "bed and breakfast", "airbnb",
    "real estate agent", "realtor",
    "locksmith", "roofer", "roofing", "landscaping", "lawn care",
    "pest control", "cleaning service", "maid service",
    "moving company", "storage facility",
    "veterinarian", "vet clinic", "animal hospital",
    "chiropractor", "physical therapy", "massage therapist",
    "painter", "painting contractor", "carpet cleaning",
    "pool service", "solar installation",
}


def classify_query(query: str) -> str:
    """Returns 'local' or 'agency'."""
    q = query.lower()

    for kw in LOCAL_KEYWORDS:
        if kw in q:
            return "local"

    for kw in AGENCY_KEYWORDS:
        if kw in q:
            return "agency"

    # Default to agency (harder to find, more likely intentional B2B search)
    return "agency"
