import os
import uuid
import logging
from typing import Dict, Any, Optional, Tuple
import httpx

logger = logging.getLogger(__name__)

SANDBOX_API_BASE = "https://api-m.sandbox.paypal.com"


def is_mock_paypal_enabled() -> bool:
    env_val = os.environ.get("MOCK_PAYPAL", "").strip().lower()
    if env_val in ("true", "1", "yes"):
        return True
    client_id = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
    secret = os.environ.get("PAYPAL_SECRET", "").strip()
    if not client_id or not secret:
        return True
    return False


CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "INR": "₹",
    "CAD": "CA$",
    "AUD": "A$",
    "JPY": "¥",
    "SGD": "S$",
}


def get_paypal_currency() -> str:
    return os.environ.get("PAYPAL_CURRENCY", "USD").strip().upper()


def get_currency_symbol(currency_code: Optional[str] = None) -> str:
    curr = (currency_code or get_paypal_currency()).upper()
    return CURRENCY_SYMBOLS.get(curr, curr)


def get_base_url() -> str:
    return os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")


async def get_access_token() -> Optional[str]:
    client_id = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
    secret = os.environ.get("PAYPAL_SECRET", "").strip()
    if not client_id or not secret:
        return None

    url = f"{SANDBOX_API_BASE}/v1/oauth2/token"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                data={"grant_type": "client_credentials"},
                auth=(client_id, secret),
                headers={
                    "Accept": "application/json",
                    "Accept-Language": "en_US"
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("access_token")
            logger.warning(f"PayPal OAuth failed: status={resp.status_code}, body={resp.text}")
            return None
    except Exception as e:
        logger.warning(f"PayPal token request exception: {e}")
        return None


async def create_paypal_order(
    amount_minor: int,
    payment_id: int,
    currency: Optional[str] = None
) -> Tuple[str, str, bool]:
    """
    Creates a PayPal order via REST API or falls back to mock approval URL.
    Returns: (order_id, approve_url, is_mock)
    """
    base_url = get_base_url()
    curr = currency or get_paypal_currency()
    formatted_amount = f"{amount_minor / 100:.2f}"
    
    # If mock mode forced or configured
    if is_mock_paypal_enabled():
        mock_id = f"MOCK-ORD-{uuid.uuid4().hex[:8].upper()}"
        mock_url = f"{base_url}/mock-pay/{payment_id}"
        return mock_id, mock_url, True

    token = await get_access_token()
    if not token:
        logger.info("No PayPal token available, falling back to mock approval URL.")
        mock_id = f"MOCK-ORD-{uuid.uuid4().hex[:8].upper()}"
        mock_url = f"{base_url}/mock-pay/{payment_id}"
        return mock_id, mock_url, True

    return_url = f"{base_url}/paypal/return"
    cancel_url = f"{base_url}/paypal/cancel"

    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": f"payment_{payment_id}",
                "amount": {
                    "currency_code": curr,
                    "value": formatted_amount
                },
                "description": f"SplitSmart AI Settlement #{payment_id}"
            }
        ],
        "application_context": {
            "return_url": return_url,
            "cancel_url": cancel_url,
            "user_action": "PAY_NOW",
            "brand_name": "SplitSmart AI"
        }
    }

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                f"{SANDBOX_API_BASE}/v2/checkout/orders",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}"
                }
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                order_id = data.get("id")
                approve_url = None
                for link in data.get("links", []):
                    if link.get("rel") == "approve":
                        approve_url = link.get("href")
                        break
                if order_id and approve_url:
                    return order_id, approve_url, False
            logger.warning(f"PayPal order creation failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.warning(f"Exception calling PayPal create order: {e}")

    # Fallback to mock on any failure
    mock_id = f"MOCK-ORD-{uuid.uuid4().hex[:8].upper()}"
    mock_url = f"{base_url}/mock-pay/{payment_id}"
    return mock_id, mock_url, True


async def capture_paypal_order(order_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Captures an approved PayPal order.
    Returns (success, response_json_or_error)
    """
    token = await get_access_token()
    if not token:
        return False, {"error": "Could not obtain PayPal token"}

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                f"{SANDBOX_API_BASE}/v2/checkout/orders/{order_id}/capture",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}"
                }
            )
            data = resp.json()
            if resp.status_code in (200, 201):
                status = data.get("status")
                if status == "COMPLETED":
                    return True, data
            return False, data
    except Exception as e:
        logger.warning(f"Error capturing PayPal order {order_id}: {e}")
        return False, {"error": str(e)}


async def get_paypal_order(order_id: str) -> Optional[Dict[str, Any]]:
    """
    Gets PayPal order status.
    """
    token = await get_access_token()
    if not token:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{SANDBOX_API_BASE}/v2/checkout/orders/{order_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code == 200:
                return resp.json()
            return None
    except Exception as e:
        logger.warning(f"Error getting PayPal order {order_id}: {e}")
        return None
