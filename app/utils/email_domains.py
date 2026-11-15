"""
Shared lists of free/public mailbox providers and UPI payment handles.

These are offline lookup tables only. They contain public provider/handle names,
not company records.
"""

FREE_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com",
    "yahoo.com", "yahoo.in", "yahoo.co.in", "ymail.com", "rocketmail.com",
    "outlook.com", "outlook.in", "hotmail.com", "live.com", "msn.com",
    "rediffmail.com", "rediff.com",
    "protonmail.com", "proton.me", "pm.me",
    "icloud.com", "me.com", "mac.com",
    "aol.com", "gmx.com", "gmx.net", "mail.com", "yandex.com", "yandex.ru",
    "zohomail.com", "zohomail.in", "tutanota.com", "tuta.io",
})

# Throwaway/temporary mailbox services (public service names; a curated list, not exhaustive).
# Companies do not send offers from these.
DISPOSABLE_EMAIL_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "guerrillamail.org", "sharklasers.com",
    "10minutemail.com", "10minutemail.net", "temp-mail.org", "temp-mail.io", "tempmail.com",
    "tempmail.net", "tempail.com", "tempr.email", "throwawaymail.com", "yopmail.com", "yopmail.net",
    "getnada.com", "maildrop.cc", "trashmail.com", "dispostable.com", "fakeinbox.com", "mohmal.com",
    "emailondeck.com", "mailnesia.com", "mytemp.email", "burnermail.io", "moakt.com", "mintemail.com",
    "discard.email", "email-fake.com", "inboxkitten.com", "anonbox.net", "spamgourmet.com",
})

# UPI virtual payment address (VPA) handles: the part after '@' in "name@ybl".
UPI_HANDLES = frozenset({
    "ybl", "ibl", "axl", "apl", "yapl", "rapl", "abfspay",
    "paytm", "ptyes", "ptaxis", "pthdfc", "ptsbi",
    "okaxis", "okhdfcbank", "okicici", "oksbi",
    "upi", "axisbank", "axisb", "icici", "sbi", "hdfcbank", "kotak", "kmbl",
    "idfcbank", "idfcfirst", "yesbank", "yesbankltd", "dlb", "fbl", "federal",
    "freecharge", "airtel", "jupiteraxis", "waaxis", "wahdfcbank", "wasbi", "waicici",
    "ikwik", "pingpay", "timecosmos", "barodampay", "unionbank", "pnb", "boi",
    "indus", "aubank", "rbl", "citi", "hsbc", "sc", "postbank", "jio",
})


def is_free_mailbox(domain: str) -> bool:
    return bool(domain) and domain.strip().lower() in FREE_EMAIL_DOMAINS


def is_disposable_mailbox(domain: str) -> bool:
    """True for a listed throwaway-mail domain or any subdomain of one (not look-alike suffixes)."""
    host = (domain or "").strip().lower().rstrip(".")
    return bool(host) and any(host == d or host.endswith("." + d) for d in DISPOSABLE_EMAIL_DOMAINS)


def is_upi_handle(domain_part: str) -> bool:
    return bool(domain_part) and domain_part.strip().lower() in UPI_HANDLES
