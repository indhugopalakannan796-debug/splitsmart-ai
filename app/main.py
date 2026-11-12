import os
import json
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional, Union

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import db, split, optimizer, ai, paypal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("splitsmart")


def get_frontend_redirect_url() -> str:
    return os.environ.get("FRONTEND_URL", "").strip().rstrip("/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database on startup
    db.init_db()
    logger.info("Database initialized successfully.")
    yield


app = FastAPI(
    title="SplitSmart AI",
    description="Intelligent bill splitting, transfer optimization, and PayPal settlement",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for split deployment (e.g. Netlify frontend + Render backend)
frontend_url = os.environ.get("FRONTEND_URL", "").strip().rstrip("/")
allowed_origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
if frontend_url and frontend_url not in allowed_origins:
    allowed_origins.append(frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if frontend_url else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static folder
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>SplitSmart AI Backend Running</h1>")


# ---------------------------------------------------------
# Configuration & Health Endpoints
# ---------------------------------------------------------

@app.get("/api/config")
async def get_config():
    curr = paypal.get_paypal_currency()
    return {
        "currency": curr,
        "currency_symbol": paypal.get_currency_symbol(curr),
        "mock_ai": ai.is_mock_ai_enabled(),
        "mock_paypal": paypal.is_mock_paypal_enabled(),
        "model": os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
        "base_url": paypal.get_base_url()
    }


class MemberPayload(BaseModel):
    name: str


@app.get("/api/members")
async def get_members():
    return db.get_members()


@app.post("/api/members", status_code=201)
async def add_member(payload: MemberPayload):
    name = (payload.name or "").strip()
    if not (1 <= len(name) <= 20):
        raise HTTPException(status_code=400, detail="Member name must be between 1 and 20 characters.")

    current = db.get_members()
    if len(current) >= 8:
        raise HTTPException(status_code=400, detail="Maximum of 8 group members allowed.")

    if any(m["name"].lower() == name.lower() for m in current):
        raise HTTPException(status_code=400, detail=f"Member with name '{name}' already exists.")

    return db.add_member(name)


@app.put("/api/members/{member_id}")
async def rename_member(member_id: int, payload: MemberPayload):
    name = (payload.name or "").strip()
    if not (1 <= len(name) <= 20):
        raise HTTPException(status_code=400, detail="Member name must be between 1 and 20 characters.")

    existing = db.get_member_by_id(member_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Member not found.")

    current = db.get_members()
    if any(m["id"] != member_id and m["name"].lower() == name.lower() for m in current):
        raise HTTPException(status_code=400, detail=f"Member with name '{name}' already exists.")

    return db.rename_member(member_id, name)


@app.delete("/api/members/{member_id}")
async def delete_member(member_id: int):
    existing = db.get_member_by_id(member_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Member not found.")

    in_use, reason = db.is_member_in_use(member_id)
    if in_use:
        raise HTTPException(status_code=409, detail=reason)

    db.delete_member(member_id)
    return {"status": "ok", "message": f"Member '{existing['name']}' deleted successfully."}


@app.post("/api/reset")
async def reset_data():
    db.reset_db()
    return {"status": "ok", "message": "Database reset and re-seeded with default members."}


# ---------------------------------------------------------
# Receipt & Assignment AI Endpoints
# ---------------------------------------------------------

@app.post("/api/receipt")
async def upload_receipt(file: UploadFile = File(...)):
    """
    Parses uploaded receipt using Gemini Vision (or mock fallback).
    Checks math discrepancy and attaches warnings.
    """
    content = await file.read()
    mime_type = file.content_type or "image/jpeg"
    parsed = ai.parse_receipt_image(content, mime_type=mime_type)
    return parsed.model_dump()


class ParseAssignmentRequest(BaseModel):
    items: List[Dict[str, Any]]
    members: List[str]
    text: str


@app.post("/api/parse-assignment")
async def parse_assignment(payload: ParseAssignmentRequest):
    """
    Parses conversational text into item assignments.
    """
    parsed = ai.parse_assignment_text(
        items=payload.items,
        members=payload.members,
        text=payload.text
    )
    return parsed.model_dump()


# ---------------------------------------------------------
# Expense & Splitting Endpoints
# ---------------------------------------------------------

class CreateExpenseRequest(BaseModel):
    description: str = "Restaurant Bill"
    paid_by: Union[int, str]
    items: List[Dict[str, Any]]
    assignments: Union[List[Dict[str, Any]], Dict[Union[str, int], List[str]]]
    tax_minor: int = 0
    discount_minor: int = 0


@app.post("/api/expenses")
async def create_expense_endpoint(payload: CreateExpenseRequest):
    """
    Computes exact fair shares and records the expense in SQLite.
    Returns breakdown per person (own items, shared part, tax part, total).
    """
    all_members = db.get_members()
    member_names = [m["name"] for m in all_members]

    # Resolve paid_by to member id and name
    paid_by_id: int
    paid_by_name: str
    if isinstance(payload.paid_by, int):
        m = db.get_member_by_id(payload.paid_by)
        if not m:
            raise HTTPException(status_code=400, detail=f"Member id {payload.paid_by} not found")
        paid_by_id = m["id"]
        paid_by_name = m["name"]
    else:
        m = db.get_member_by_name(str(payload.paid_by))
        if not m:
            m = db.get_or_create_member(str(payload.paid_by))
        paid_by_id = m["id"]
        paid_by_name = m["name"]

    try:
        split_result = split.compute_shares(
            items=payload.items,
            assignments=payload.assignments,
            tax_minor=payload.tax_minor,
            discount_minor=payload.discount_minor,
            members=member_names
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Split error: {str(e)}")

    total_minor = split_result["total_minor"]
    shares = split_result["shares"]

    expense_id = db.create_expense(
        description=payload.description,
        paid_by=paid_by_id,
        total_minor=total_minor,
        items_json=json.dumps(payload.items),
        assignments_json=json.dumps(payload.assignments),
        shares_json=json.dumps(shares)
    )

    return {
        "expense_id": expense_id,
        "description": payload.description,
        "paid_by": {"id": paid_by_id, "name": paid_by_name},
        "total_minor": total_minor,
        "tax_minor": split_result["tax_minor"],
        "discount_minor": split_result["discount_minor"],
        "shares": shares,
        "breakdown": split_result["breakdown"]
    }


@app.get("/api/expenses")
async def get_expenses_endpoint():
    expenses = db.get_expenses()
    formatted = []
    for exp in expenses:
        exp_dict = dict(exp)
        exp_dict["items"] = json.loads(exp_dict.get("items_json", "[]"))
        exp_dict["assignments"] = json.loads(exp_dict.get("assignments_json", "[]"))
        exp_dict["shares"] = json.loads(exp_dict.get("shares_json", "{}"))
        formatted.append(exp_dict)
    return formatted


# ---------------------------------------------------------
# Balances & Settlement Plan Endpoints
# ---------------------------------------------------------

@app.get("/api/balances")
async def get_balances_endpoint():
    expenses = db.get_expenses()
    all_members = db.get_members()
    member_names = [m["name"] for m in all_members]

    exp_list = []
    for exp in expenses:
        exp_dict = dict(exp)
        exp_dict["shares"] = json.loads(exp_dict.get("shares_json", "{}"))
        exp_list.append(exp_dict)

    net_balances, raw_count = optimizer.calculate_net_balances(exp_list, member_names)
    return {
        "balances": net_balances,
        "raw_transfers_count": raw_count,
        "currency": paypal.get_paypal_currency()
    }


@app.get("/api/settlement-plan")
async def get_settlement_plan():
    """
    Computes reduced transfers using greedy creditor-debtor matching across all expenses.
    Returns transfers and count before vs after.
    """
    expenses = db.get_expenses()
    all_members = db.get_members()
    member_names = [m["name"] for m in all_members]

    exp_list = []
    for exp in expenses:
        exp_dict = dict(exp)
        exp_dict["shares"] = json.loads(exp_dict.get("shares_json", "{}"))
        exp_list.append(exp_dict)

    net_balances, raw_count = optimizer.calculate_net_balances(exp_list, member_names)
    reduced_transfers = optimizer.optimize_transfers(net_balances)

    # Attach existing payment record status if already generated
    existing_payments = db.get_payments()
    for t in reduced_transfers:
        matching = next(
            (p for p in existing_payments if p["from_name"] == t["from"] and p["to_name"] == t["to"] and p["amount_minor"] == t["amount_minor"]),
            None
        )
        if matching:
            t["payment_id"] = matching["id"]
            t["status"] = matching["status"]
            t["approve_url"] = matching["approve_url"]
            t["paypal_order_id"] = matching["paypal_order_id"]
        else:
            t["status"] = "uncreated"
            t["payment_id"] = None
            t["approve_url"] = None
            t["paypal_order_id"] = None

    return {
        "net_balances": net_balances,
        "transfers": reduced_transfers,
        "before_count": raw_count,
        "after_count": len(reduced_transfers),
        "currency": paypal.get_paypal_currency()
    }


# ---------------------------------------------------------
# PayPal & Payments Endpoints
# ---------------------------------------------------------

class CreatePaymentRequest(BaseModel):
    from_name: Optional[str] = Field(default=None, alias="from")
    to_name: Optional[str] = Field(default=None, alias="to")
    from_member: Optional[str] = None
    to_member: Optional[str] = None
    amount_minor: int
    expense_id: Optional[int] = None


@app.post("/api/payments/create")
async def create_payment_endpoint(payload: CreatePaymentRequest):
    """
    Creates a PayPal order via direct REST API or mock approval page.
    """
    sender_name = payload.from_name or payload.from_member
    receiver_name = payload.to_name or payload.to_member
    if not sender_name or not receiver_name:
        raise HTTPException(status_code=400, detail="'from' and 'to' member names are required")

    from_mem = db.get_or_create_member(sender_name)
    to_mem = db.get_or_create_member(receiver_name)

    # Pre-create payment record
    payment_id = db.create_payment(
        expense_id=payload.expense_id,
        from_member=from_mem["id"],
        to_member=to_mem["id"],
        amount_minor=payload.amount_minor,
        status="pending"
    )

    order_id, approve_url, is_mock = await paypal.create_paypal_order(
        amount_minor=payload.amount_minor,
        payment_id=payment_id
    )

    db.update_payment(
        payment_id=payment_id,
        status="pending",
        paypal_order_id=order_id,
        approve_url=approve_url
    )

    return {
        "payment_id": payment_id,
        "from": sender_name,
        "to": receiver_name,
        "amount_minor": payload.amount_minor,
        "paypal_order_id": order_id,
        "approve_url": approve_url,
        "status": "pending",
        "is_mock": is_mock
    }


@app.get("/api/payments")
async def get_payments_list():
    return db.get_payments()


@app.post("/api/payments/{payment_id}/refresh")
async def refresh_payment_status(payment_id: int):
    """
    Checks PayPal order status and marks as paid if completed or approved.
    """
    payment = db.get_payment(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    order_id = payment.get("paypal_order_id")
    if not order_id:
        return payment

    if order_id.startswith("MOCK-"):
        # Mock payment status remains as in DB unless confirmed
        return payment

    # Real PayPal check
    order_data = await paypal.get_paypal_order(order_id)
    if order_data:
        status = order_data.get("status")
        if status == "COMPLETED":
            db.update_payment(payment_id, status="paid")
        elif status == "APPROVED":
            # Attempt to capture
            success, _ = await paypal.capture_paypal_order(order_id)
            if success:
                db.update_payment(payment_id, status="paid")

    return db.get_payment(payment_id)


@app.get("/paypal/return")
async def paypal_return(token: Optional[str] = None):
    """
    PayPal redirects here after user approval. Captures order and marks paid.
    """
    if token:
        success, _ = await paypal.capture_paypal_order(token)
        if success:
            db.update_payment_by_order_id(token, "paid")
        else:
            # Even if capture returns already captured, mark paid if completed
            order = await paypal.get_paypal_order(token)
            if order and order.get("status") in ("COMPLETED", "APPROVED"):
                db.update_payment_by_order_id(token, "paid")

    frontend = get_frontend_redirect_url()
    redirect_target = f"{frontend}/?step=settle&paid=1" if frontend else "/?step=settle&paid=1"
    return RedirectResponse(url=redirect_target, status_code=303)


@app.get("/paypal/cancel")
async def paypal_cancel():
    frontend = get_frontend_redirect_url()
    redirect_target = f"{frontend}/?payment=cancelled" if frontend else "/?payment=cancelled"
    return RedirectResponse(url=redirect_target, status_code=303)


@app.post("/api/paypal/webhook")
async def paypal_webhook(request: Request):
    """
    PayPal Webhook endpoint.
    On PAYMENT.CAPTURE.COMPLETED, marks payment as paid.
    TODO: Verify PayPal webhook cryptographic signature (headers: PAYPAL-AUTH-ALGO, PAYPAL-CERT-URL, etc.) in production.
    """
    try:
        body = await request.json()
        event_type = body.get("event_type")
        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            resource = body.get("resource", {})
            supplementary_data = resource.get("supplementary_data", {})
            related_ids = supplementary_data.get("related_ids", {})
            order_id = related_ids.get("order_id")
            if order_id:
                db.update_payment_by_order_id(order_id, "paid")
        return {"status": "ok"}
    except Exception as e:
        logger.warning(f"Error handling webhook: {e}")
        return {"status": "error", "detail": str(e)}


# ---------------------------------------------------------
# Mock Payment Approval Page (/mock-pay/{id})
# ---------------------------------------------------------

@app.get("/mock-pay/{payment_id}", response_class=HTMLResponse)
async def mock_pay_page(payment_id: int):
    payment = db.get_payment(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found")

    currency = paypal.get_paypal_currency()
    amount_fmt = f"{payment['amount_minor'] / 100:.2f}"

    frontend = get_frontend_redirect_url()
    back_url = f"{frontend}/?step=settle" if frontend else "/?step=settle"

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>PayPal Sandbox Simulation - SplitSmart AI</title>
      <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-50 min-h-screen flex items-center justify-center p-4">
      <div class="max-w-md w-full bg-white rounded-2xl shadow-xl border border-slate-200 overflow-hidden">
        <!-- PayPal-like Header -->
        <div class="bg-[#003087] text-white p-6 text-center relative">
          <span class="absolute top-3 right-3 bg-amber-400 text-amber-950 text-xs font-bold px-2 py-0.5 rounded-full">MOCK SANDBOX</span>
          <h2 class="text-2xl font-black tracking-tight italic">PayPal <span class="text-[#0079C1] font-normal not-italic text-sm">Sandbox</span></h2>
          <p class="text-xs text-blue-200 mt-1">SplitSmart AI Payment Simulation</p>
        </div>

        <div class="p-6 space-y-6">
          <div class="bg-blue-50 border border-blue-100 rounded-xl p-4 text-center">
            <p class="text-xs font-medium text-blue-600 uppercase tracking-wider">Amount to Pay</p>
            <p class="text-3xl font-extrabold text-blue-950 mt-1">{currency} {amount_fmt}</p>
          </div>

          <div class="divide-y divide-slate-100 text-sm">
            <div class="py-2.5 flex justify-between">
              <span class="text-slate-500">From (Debtor):</span>
              <span class="font-semibold text-slate-800">{payment['from_name']}</span>
            </div>
            <div class="py-2.5 flex justify-between">
              <span class="text-slate-500">To (Creditor):</span>
              <span class="font-semibold text-slate-800">{payment['to_name']}</span>
            </div>
            <div class="py-2.5 flex justify-between">
              <span class="text-slate-500">Order ID:</span>
              <span class="font-mono text-xs text-slate-600">{payment['paypal_order_id']}</span>
            </div>
            <div class="py-2.5 flex justify-between">
              <span class="text-slate-500">Current Status:</span>
              <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold {'bg-emerald-100 text-emerald-800' if payment['status'] == 'paid' else 'bg-amber-100 text-amber-800'}">
                {payment['status'].upper()}
              </span>
            </div>
          </div>

          {'<div class="bg-emerald-50 border border-emerald-200 text-emerald-800 p-4 rounded-xl text-center font-medium">This payment is already marked as PAID!</div>' if payment['status'] == 'paid' else f'''
          <form method="POST" action="/mock-pay/{payment_id}/confirm">
            <button type="submit" class="w-full bg-[#0070BA] hover:bg-[#003087] text-white font-bold py-3.5 px-6 rounded-xl shadow-md transition duration-150 flex items-center justify-center space-y-0 space-x-2">
              <span>Pay {currency} {amount_fmt} (Simulate Approval)</span>
            </button>
          </form>
          '''}

          <div class="text-center pt-2">
            <a href="{back_url}" class="text-xs text-slate-400 hover:text-slate-600 font-medium">← Back to SplitSmart</a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/mock-pay/{payment_id}")
@app.post("/mock-pay/{payment_id}/confirm")
async def confirm_mock_payment(payment_id: int):
    payment = db.get_payment(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    db.update_payment(payment_id, status="paid")
    frontend = get_frontend_redirect_url()
    redirect_target = f"{frontend}/?step=settle&paid=1" if frontend else "/?step=settle&paid=1"
    return RedirectResponse(url=redirect_target, status_code=303)


# ---------------------------------------------------------
# Reminder AI Endpoint
# ---------------------------------------------------------

class ReminderRequest(BaseModel):
    payment_id: Optional[int] = None
    from_name: Optional[str] = None
    to_name: Optional[str] = None
    amount_minor: Optional[int] = None
    tone: str = "friendly"


@app.post("/api/reminder")
async def reminder_endpoint(payload: ReminderRequest):
    """
    Generates personalized reminder text via Gemini or template mock.
    """
    currency = paypal.get_paypal_currency()
    from_name = payload.from_name or "Friend"
    to_name = payload.to_name or "Me"
    amount_str = ""
    description = "Recent Outing"
    approve_url = ""

    if payload.payment_id:
        p = db.get_payment(payload.payment_id)
        if p:
            from_name = p["from_name"]
            to_name = p["to_name"]
            amount_str = f"{currency} {p['amount_minor'] / 100:.2f}"
            approve_url = p.get("approve_url") or ""
            if p.get("expense_id"):
                exp = db.get_expense(p["expense_id"])
                if exp and exp.get("description"):
                    description = exp["description"]

    if not amount_str and payload.amount_minor is not None:
        amount_str = f"{currency} {payload.amount_minor / 100:.2f}"

    reminder_data = ai.generate_reminder_message(
        from_name=from_name,
        to_name=to_name,
        amount_str=amount_str,
        description=description,
        tone=payload.tone,
        pay_url=approve_url
    )
    return reminder_data
