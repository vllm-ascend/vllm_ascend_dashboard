"""
Company detection from email domain.

Maps email domains to company display names. Extensible -- add new entries to COMPANY_DOMAIN_MAP.
Supports subdomains: user@sz.huawei.com matches "huawei.com" → "华为"
"""

COMPANY_DOMAIN_MAP: dict[str, str] = {
    "huawei.com": "华为",
}


def detect_company(email: str | None) -> str | None:
    """
    Detect company affiliation from an email address.

    Args:
        email: The email address to check, or None.

    Returns:
        Company display name if the domain matches a known company, None otherwise.
        Supports subdomain matching: user@sz.huawei.com matches the "huawei.com" entry.
    """
    if not email or "@" not in email:
        return None

    domain = email.rsplit("@", 1)[-1].lower().strip()

    # Exact match first
    if domain in COMPANY_DOMAIN_MAP:
        return COMPANY_DOMAIN_MAP[domain]

    # Subdomain match: check if domain ends with any known domain
    for known_domain, company_name in COMPANY_DOMAIN_MAP.items():
        if domain.endswith("." + known_domain) or domain == known_domain:
            return company_name

    return None
