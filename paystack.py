"""
paystack.py — Paystack API integration
Handles payment initialization and verification via Paystack's REST API.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
BASE_URL = "https://api.paystack.co"

HEADERS = {
    "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
    "Content-Type": "application/json",
}


def initialize_payment(
    email: str,
    amount_naira: int,
    reference: str,
    metadata: dict,
) -> dict:
    """
    Create a Paystack payment link.
    Amount is supplied in Naira and converted to kobo (×100) here.
    Returns the full Paystack API response dict.
    """
    payload = {
        "email": email,
        "amount": amount_naira * 100,   # Paystack expects kobo
        "reference": reference,
        "metadata": metadata,
        "currency": "NGN",
    }
    try:
        response = requests.post(
            f"{BASE_URL}/transaction/initialize",
            json=payload,
            headers=HEADERS,
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        logger.error("Paystack initialize_payment error: %s", exc)
        return {"status": False, "message": str(exc)}


def verify_payment(reference: str) -> dict:
    """
    Verify a transaction using its reference code.
    Returns the full Paystack API response dict.
    Check result["data"]["status"] == "success" for confirmation.
    """
    try:
        response = requests.get(
            f"{BASE_URL}/transaction/verify/{reference}",
            headers=HEADERS,
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        logger.error("Paystack verify_payment error: %s", exc)
        return {"status": False, "message": str(exc)}
