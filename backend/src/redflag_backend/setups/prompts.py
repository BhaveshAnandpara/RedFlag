"""Small helpers for putting untrusted text into a prompt as data."""

import secrets


def fence(label: str, text: str) -> str:
    """The text between lines that carry a fresh random marker, so it cannot close its own fence."""
    while True:
        marker = secrets.token_hex(8)
        if marker not in text:
            break
    return f"<<<{label} {marker}\n{text}\n{marker}>>>"
