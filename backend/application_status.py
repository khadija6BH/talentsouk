"""Shared interpretation of application states; legacy Applied is not proof of sending."""
from collections import Counter

APPLICATION_STATUSES = ["Wishlist", "Draft", "Sent", "Replied", "Interview", "Accepted", "Rejected"]
LEGACY_STATUSES = {"Prepared": "Draft", "Target": "Draft", "Saved": "Draft", "Applied": "Draft", "Contacted": "Draft", "Discovered": "Draft", "Wishlisted": "Wishlist", "Outreach Sent": "Sent", "Reply Received": "Replied", "Interview Scheduled": "Interview", "Offer Received": "Accepted"}
_STATUS_LOOKUP = {name.casefold(): name for name in APPLICATION_STATUSES}
_STATUS_LOOKUP.update({old.casefold(): new for old, new in LEGACY_STATUSES.items()})

def normalize_application_status(status):
    return _STATUS_LOOKUP.get(str(status or "").strip().casefold(), "Draft")

def application_counts(records):
    counts = Counter(normalize_application_status(row["status"]) for row in records)
    return {status: counts[status] for status in APPLICATION_STATUSES}
