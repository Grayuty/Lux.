"""
utils.py — Shared helper functions
Token generation, currency formatting, etc.
"""

import random
import string


def generate_token() -> str:
    """
    Generate a unique pickup token in the format MAT-XXXXXX
    where X is an uppercase letter or digit.
    Example: MAT-7F3K2P
    """
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=6))
    return f"MAT-{suffix}"


def format_naira(amount: int) -> str:
    """Format an integer amount as Nigerian Naira. E.g. 2000 → ₦2,000"""
    return f"₦{amount:,}"


def truncate(text: str, max_len: int = 200) -> str:
    """Truncate long strings for display in Telegram messages."""
    return text if len(text) <= max_len else text[: max_len - 3] + "..."
