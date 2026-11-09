import os
import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Built-in Demo Data (values in minor units: paise / cents)
DEMO_RECEIPT_ITEMS = [
    {"id": 1, "name": "Masala Dosa", "price_minor": 10000, "qty": 1},
    {"id": 2, "name": "Filter Coffee", "price_minor": 6000, "qty": 1},
    {"id": 3, "name": "Chicken Biryani", "price_minor": 25000, "qty": 1},
    {"id": 4, "name": "Lime Soda", "price_minor": 6000, "qty": 1},
    {"id": 5, "name": "Veg Fried Rice", "price_minor": 18000, "qty": 1},
    {"id": 6, "name": "Gobi Manchurian", "price_minor": 15000, "qty": 1},
    {"id": 7, "name": "Paneer Pizza", "price_minor": 30000, "qty": 1},
    {"id": 8, "name": "Cold Coffee", "price_minor": 10000, "qty": 1},
    {"id": 9, "name": "Gulab Jamun", "price_minor": 10000, "qty": 1},
]
DEMO_TAX_MINOR = 6500       # GST 5% = 65
DEMO_DISCOUNT_MINOR = 0
DEMO_TOTAL_MINOR = 136500   # Total 1365

DEMO_ASSIGNMENTS = [
    {"item_id": 1, "people": ["Indhu"]},
    {"item_id": 2, "people": ["Indhu"]},
    {"item_id": 3, "people": ["Ravi"]},
    {"item_id": 4, "people": ["Ravi"]},
    {"item_id": 5, "people": ["Priya"]},
    {"item_id": 6, "people": ["Priya"]},
    {"item_id": 7, "people": ["Karthik"]},
    {"item_id": 8, "people": ["Karthik"]},
    {"item_id": 9, "people": ["Indhu", "Ravi", "Priya", "Karthik"]},
]


class ReceiptItem(BaseModel):
    id: Optional[Any] = 1
    name: str
    price_minor: int
    qty: int = 1


class ReceiptParsed(BaseModel):
    items: List[ReceiptItem] = Field(default_factory=list)
    tax_minor: int = 0
    discount_minor: int = 0
    total_minor: int = 0
    warnings: List[str] = Field(default_factory=list)
    is_mock: bool = False


class AssignmentItem(BaseModel):
    item_id: Any
    people: List[str] = Field(default_factory=list)


class AssignmentParsed(BaseModel):
    assignments: List[AssignmentItem] = Field(default_factory=list)
    is_mock: bool = False


def is_mock_ai_enabled() -> bool:
    env_val = os.environ.get("MOCK_AI", "").strip().lower()
    if env_val in ("true", "1", "yes"):
        return True
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        return True
    return False


def _get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as e:
        logger.warning(f"Could not initialize google-genai Client: {e}")
        return None


def parse_receipt_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> ReceiptParsed:
    """
    Parses receipt image using Gemini Vision or falls back to demo data.
    Validates with Pydantic and checks if sum(items) + tax - discount == total.
    """
    if is_mock_ai_enabled():
        return _get_demo_receipt(is_mock=True)

    client = _get_gemini_client()
    if not client:
        return _get_demo_receipt(is_mock=True)

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()
    prompt = """
You are an expert restaurant receipt parser. Analyze the receipt image and extract:
1. All line items with their names, quantities, and price in integer minor units (e.g. cents/paise: multiply currency by 100).
2. Tax amount in minor units.
3. Discount amount in minor units (0 if none).
4. Stated final total in minor units.

Respond ONLY with a valid JSON object matching this exact schema:
{
  "items": [
    {"id": 1, "name": "Item Name", "price_minor": 1000, "qty": 1}
  ],
  "tax_minor": 150,
  "discount_minor": 0,
  "total_minor": 1150
}
Do not include any explanation or markdown formatting. Output raw JSON only.
"""
    try:
        from google.genai import types
        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt
            ]
        )
        text = response.text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        data = json.loads(text)
        items = [
            ReceiptItem(
                id=item.get("id", idx + 1),
                name=str(item.get("name", f"Item {idx + 1}")),
                price_minor=int(item.get("price_minor", 0)),
                qty=int(item.get("qty", 1))
            )
            for idx, item in enumerate(data.get("items", []))
        ]
        tax_minor = int(data.get("tax_minor", 0))
        discount_minor = int(data.get("discount_minor", 0))
        total_minor = int(data.get("total_minor", 0))

        # Check math discrepancy
        calc_total = sum(i.price_minor * i.qty for i in items) + tax_minor - discount_minor
        warnings = []
        if calc_total != total_minor:
            warnings.append(
                f"Receipt math mismatch: calculated ({calc_total}) != printed total ({total_minor}). Check line items."
            )

        return ReceiptParsed(
            items=items,
            tax_minor=tax_minor,
            discount_minor=discount_minor,
            total_minor=total_minor,
            warnings=warnings,
            is_mock=False
        )
    except Exception as e:
        logger.warning(f"Gemini receipt parsing failed ({e}), falling back to mock demo data.")
        demo = _get_demo_receipt(is_mock=True)
        demo.warnings.append(f"AI parsing unavailable ({str(e)[:60]}); loaded demo receipt.")
        return demo


def _get_demo_receipt(is_mock: bool = True) -> ReceiptParsed:
    items = [ReceiptItem(**item) for item in DEMO_RECEIPT_ITEMS]
    calc_total = sum(i.price_minor * i.qty for i in items) + DEMO_TAX_MINOR - DEMO_DISCOUNT_MINOR
    warnings = []
    if calc_total != DEMO_TOTAL_MINOR:
        warnings.append(
            f"Receipt math mismatch: calculated ({calc_total}) != printed total ({DEMO_TOTAL_MINOR})."
        )
    return ReceiptParsed(
        items=items,
        tax_minor=DEMO_TAX_MINOR,
        discount_minor=DEMO_DISCOUNT_MINOR,
        total_minor=DEMO_TOTAL_MINOR,
        warnings=warnings,
        is_mock=is_mock
    )


def parse_assignment_text(
    items: List[Dict[str, Any]],
    members: List[str],
    text: str
) -> AssignmentParsed:
    """
    Parses conversational assignment (e.g. 'Indhu had dosa and coffee, everyone shared gulab jamun')
    into assignments JSON via Gemini, or falls back to demo logic / demo assignment.
    """
    if is_mock_ai_enabled():
        return _fallback_assignment(items, members, text, is_mock=True)

    client = _get_gemini_client()
    if not client:
        return _fallback_assignment(items, members, text, is_mock=True)

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()
    prompt = f"""
You are an intelligent bill splitting assistant.
Match items on the bill to the people mentioned in the user's sentence.

Available bill items:
{json.dumps([{"id": item.get("id"), "name": item.get("name")} for item in items], indent=2)}

Available group members:
{json.dumps(members, indent=2)}

User statement:
"{text}"

Rules:
1. For each item in the bill, decide which members should be assigned to it based on the user's statement.
2. Words like 'everyone', 'all of us', 'shared by all' mean all available group members.
3. If an item is not explicitly mentioned, you may assign it to everyone or leave its people list empty.
4. Output ONLY a valid JSON object matching this exact structure:
{{
  "assignments": [
    {{"item_id": 1, "people": ["Indhu"]}},
    {{"item_id": 9, "people": ["Indhu", "Ravi", "Priya", "Karthik"]}}
  ]
}}
Do not include markdown backticks or commentary. Raw JSON only.
"""
    try:
        response = client.models.generate_content(model=model_name, contents=prompt)
        res_text = response.text.strip()
        if res_text.startswith("```"):
            lines = res_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            res_text = "\n".join(lines).strip()

        data = json.loads(res_text)
        assignments = [
            AssignmentItem(
                item_id=a.get("item_id"),
                people=[p for p in a.get("people", []) if p in members]
            )
            for a in data.get("assignments", [])
        ]
        return AssignmentParsed(assignments=assignments, is_mock=False)
    except Exception as e:
        logger.warning(f"Gemini assignment parsing failed ({e}), falling back to heuristic/demo.")
        return _fallback_assignment(items, members, text, is_mock=True)


def _fallback_assignment(
    items: List[Dict[str, Any]],
    members: List[str],
    text: str,
    is_mock: bool = True
) -> AssignmentParsed:
    lower_text = text.lower()
    # Check if text aligns with the demo assignment
    if any(k in lower_text for k in ["dosa", "biryani", "gulab jamun", "indhu", "ravi", "priya", "karthik"]):
        # Match demo items by name or id
        assignments = []
        for item in items:
            name_low = str(item.get("name", "")).lower()
            item_id = item.get("id")
            if "dosa" in name_low or "filter coffee" in name_low:
                assignments.append(AssignmentItem(item_id=item_id, people=["Indhu"]))
            elif "biryani" in name_low or "soda" in name_low:
                assignments.append(AssignmentItem(item_id=item_id, people=["Ravi"]))
            elif "fried rice" in name_low or "manchurian" in name_low:
                assignments.append(AssignmentItem(item_id=item_id, people=["Priya"]))
            elif "pizza" in name_low or "cold coffee" in name_low:
                assignments.append(AssignmentItem(item_id=item_id, people=["Karthik"]))
            elif "jamun" in name_low:
                assignments.append(AssignmentItem(item_id=item_id, people=[m for m in ["Indhu", "Ravi", "Priya", "Karthik"] if m in members]))
            else:
                assignments.append(AssignmentItem(item_id=item_id, people=members))
        return AssignmentParsed(assignments=assignments, is_mock=is_mock)

    # Simple heuristic fallback: assign items to mentioned members or everyone
    assignments = []
    for item in items:
        assignments.append(AssignmentItem(item_id=item.get("id"), people=members))
    return AssignmentParsed(assignments=assignments, is_mock=is_mock)


def generate_reminder_message(
    from_name: str,
    to_name: str,
    amount_str: str,
    description: str,
    tone: str = "friendly",
    pay_url: str = ""
) -> Dict[str, Any]:
    """
    Generates a personalized payment reminder in the requested tone.
    """
    url_snippet = f"Pay here: {pay_url}" if pay_url else "Check the app to settle up."
    
    if is_mock_ai_enabled():
        txt = _mock_reminder_text(from_name, to_name, amount_str, description, tone, url_snippet)
        return {
            "message": txt,
            "reminder": txt,
            "is_mock": True
        }

    client = _get_gemini_client()
    if not client:
        txt = _mock_reminder_text(from_name, to_name, amount_str, description, tone, url_snippet)
        return {
            "message": txt,
            "reminder": txt,
            "is_mock": True
        }

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()
    prompt = f"""
Write a short, engaging 1-2 sentence payment reminder message to send to a friend via SMS or WhatsApp.
- Debtor (person who owes): {from_name}
- Creditor (person to receive): {to_name}
- Amount: {amount_str}
- Event / Description: {description}
- Tone required: {tone} (friendly, firm, or funny)
- Payment link: {url_snippet}

Output ONLY the text message. No quotation marks, no preamble.
"""
    try:
        response = client.models.generate_content(model=model_name, contents=prompt)
        msg = response.text.strip()
        return {
            "message": msg,
            "reminder": msg,
            "is_mock": False
        }
    except Exception as e:
        logger.warning(f"Gemini reminder generation failed ({e}), falling back to template.")
        txt = _mock_reminder_text(from_name, to_name, amount_str, description, tone, url_snippet)
        return {
            "message": txt,
            "reminder": txt,
            "is_mock": True
        }


def _mock_reminder_text(from_name: str, to_name: str, amount_str: str, description: str, tone: str, url_snippet: str) -> str:
    desc_str = f" for '{description}'" if description else ""
    if tone == "firm":
        return f"Hi {from_name}, this is a gentle reminder to settle your balance of {amount_str}{desc_str}. Please clear it when you can: {url_snippet}"
    elif tone == "funny":
        return f"Hey {from_name}! Rumor has it our feast{desc_str} tasted 10x better than debt feels! Clear your share of {amount_str} here before interest gets charged in pizza slices: {url_snippet} 🍕"
    else:  # friendly
        return f"Hey {from_name}! Just a quick ping about your split of {amount_str}{desc_str} to {to_name}. No rush, whenever you get a second: {url_snippet} 😊"
