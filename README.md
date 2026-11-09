# SplitSmart AI ⚡

> **Intelligent receipt OCR, conversational item assignment, mathematically fair proportional splitting, transfer reduction, and PayPal Sandbox settlement tracking in ONE pass.**

SplitSmart AI is a hackathon-ready, full-stack web application designed to eliminate the awkwardness and mathematical chaos of dining out with friends. It takes a receipt image, assigns items naturally via English sentences or an interactive matrix, splits taxes and discounts proportionally down to the exact paise/cent using the **Largest Remainder Method**, reduces net balances across multiple expenses using **greedy creditor-debtor matching**, and facilitates direct checkout via **PayPal Orders v2 REST API**.

---

## 🌟 Key Features

1. **AI Receipt OCR (Gemini Vision)**:
   - Upload any photo of a restaurant receipt or bill.
   - Analyzed using `google-genai` (default: `gemini-2.0-flash`).
   - Extracts line items, quantities, subtotal, tax, and discounts in integer minor units (paise/cents).
   - Built-in math integrity check: raises a warning if item sum + tax - discount != total.
2. **Conversational Item Assignment**:
   - Natural language input: *"Indhu had dosa and coffee, Ravi had biryani and soda, everyone shared gulab jamun"*.
   - Automatically mapped to group members using Gemini NLP or fallback heuristics.
   - Real-time interactive person × item checkbox matrix for instant manual overrides.
3. **Mathematically Exact Fair Split (`split.py`)**:
   - Zero float rounding errors: stores all money in integer minor units.
   - Supports partial group participation (e.g., 3 of 5 people sharing a dish).
   - Proportional tax and discount distribution based on individual pre-tax consumption.
   - **Largest Remainder Method (Hare-Niemeyer)** guarantees that the sum of all individual shares equals the printed bill total down to the single integer unit.
4. **Multi-Expense Debt Simplification (`optimizer.py`)**:
   - Track multiple expenses across different payers in a single session.
   - Aggregates net balances into a unified creditor-debtor ledger.
   - Heuristic greedy matching reduces the total number of transactions required to settle all debts.
5. **PayPal Sandbox Integration (`paypal.py`)**:
   - Direct HTTP calls via `httpx` to PayPal Orders v2 Sandbox REST API (no SDK required).
   - Automatic OAuth2 token caching, order creation (`intent: CAPTURE`), and capture on return.
   - Real-time status refresh, webhooks (`PAYMENT.CAPTURE.COMPLETED`), and local mock fallback simulation (`/mock-pay/{id}`).
6. **AI Payment Reminder Generator**:
   - Generates personalized SMS/WhatsApp payment reminder texts with links in **Friendly**, **Firm**, or **Funny** tones.

---

## 🏗️ System Architecture

```
               ┌────────────────────────────────────────────────────────┐
               │              FastAPI Backend (app/main.py)             │
               └────┬──────────────┬───────────────┬───────────────┬────┘
                    │              │               │               │
     ┌──────────────▼───┐   ┌──────▼──────┐   ┌────▼────────┐  ┌───▼──────────┐
     │   Google Gemini  │   │  Core Split │   │  Optimizer  │  │    PayPal    │
     │     (app/ai.py)  │   │(app/split.py│   │(optimizer.py│  │ (app/paypal.py│
     └──────────────────┘   └─────────────┘   └─────────────┘  └──────────────┘
              ▲                    ▲                 ▲                 ▲
              │                    │                 │                 │
              └────────────────────┴────────┬────────┴─────────────────┘
                                            │
                             ┌──────────────▼─────────────┐
                             │ SQLite Database(app/db.py) │
                             │  (members, expenses, pay)  │
                             └────────────────────────────┘
```

---

## ⚙️ Quickstart & Local Setup

### Prerequisites
- Python 3.11 or Python 3.12
- Internet access (for PayPal Sandbox & Gemini APIs, or run offline via mock flags)

### 1. Clone & Create Virtual Environment
```bash
# Clone the repository
git clone https://github.com/your-username/splitsmart-ai.git
cd splitsmart-ai

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# macOS/Linux:
source venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
```bash
# Copy template
cp .env.example .env
```

Edit `.env` with your preferred settings:
```env
# Google Gemini AI Configuration
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.0-flash

# PayPal Sandbox Configuration
PAYPAL_CLIENT_ID=your_paypal_sandbox_client_id
PAYPAL_SECRET=your_paypal_sandbox_secret
PAYPAL_CURRENCY=USD

# Server URL for PayPal Return / Cancel Webhooks
BASE_URL=http://localhost:8000

# Frontend URL (for split deployment on Netlify / CORS & payment redirects)
FRONTEND_URL=http://localhost:8000

# Mock Flags (set true to force mock mode, or leave false to use real APIs with fallback)
MOCK_AI=false
MOCK_PAYPAL=false
```

### 4. Run the Application
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Open your browser at **[http://localhost:8000](http://localhost:8000)**.

---

## 🧪 Running Automated Tests

Run the complete test suite using `pytest`:
```bash
pytest
```
Expected output:
```text
tests/test_split.py ...                                              [ 60%]
tests/test_optimizer.py ..                                           [100%]
============================== 5 passed in 0.15s ==============================
```

Tests verify:
- Exact sum match (136500 minor units) for the demo receipt with 5% GST.
- Partial participation (3 of 5 people sharing a boat ride).
- Largest remainder rounding on awkward divisions (e.g. 100 split 3 ways).
- Transfer optimizer zeroing out net balances `{Indhu:+500, Ravi:+200, Priya:-400, Karthik:-200, Arun:-100}` with at most 4 transfers.

---

## 💳 PayPal Sandbox Setup Guide

To test real PayPal Sandbox payments without real money:

1. **Log in to PayPal Developer Portal**:
   - Go to [developer.paypal.com](https://developer.paypal.com/) and sign in with your PayPal account.
2. **Create Sandbox Test Accounts**:
   - Go to **Testing Tools** ➔ **Sandbox Accounts**.
   - Ensure you have two accounts:
     - **Business Account (Merchant)**: Represents the recipient.
     - **Personal Account (Buyer)**: Used to log in and pay during simulated checkout. Note its email and password.
3. **Create REST API App Credentials**:
   - Go to **Apps & Credentials** ➔ select the **Sandbox** tab.
   - Click **Create App**, give it a name (e.g. `SplitSmart`), and assign it to your Sandbox Business account.
   - Copy the **Client ID** and **Secret** into your `.env` file (`PAYPAL_CLIENT_ID`, `PAYPAL_SECRET`).
4. **Testing Payment**:
   - Click "Create PayPal link" in SplitSmart AI.
   - Click "Pay with PayPal".
   - On the PayPal login screen, enter your Sandbox **Personal Account** email and password.
   - Click **Complete Purchase**; you will be redirected back to SplitSmart AI with the payment marked **PAID**.

---

## 🛡️ Offline & Mock Modes

SplitSmart AI is designed to be 100% resilient during hackathons and live demos:

- If `MOCK_AI=true` or if `GEMINI_API_KEY` is not provided or fails, the app uses built-in demo data (South Indian restaurant feast totaling ₹1,365) and heuristic NLP mapping.
- If `MOCK_PAYPAL=true` or if PayPal credentials are missing or fail, the app creates a simulated approval link pointing to `/mock-pay/{payment_id}` with a simulated PayPal approval button.
- Whenever a mock path is used, a prominent **MOCK** badge is displayed in the UI.

---

## 🌐 Split Deployment (Netlify Frontend + Render Backend)

SplitSmart AI supports clean separated deployment with zero build steps:

### 1. Deploy Backend on Render
1. Push this repository to GitHub.
2. In Render, create a new **Web Service** (or use the Blueprint with `render.yaml`).
3. Set the Environment Variables:
   - `FRONTEND_URL`: your Netlify URL (e.g. `https://your-app.netlify.app`).
   - `BASE_URL`: your Render backend URL (e.g. `https://your-backend.onrender.com`).
   - `GEMINI_API_KEY`, `PAYPAL_CLIENT_ID`, `PAYPAL_SECRET`, etc.
4. The backend automatically applies CORS middleware for `FRONTEND_URL` and redirects PayPal returns & mock approvals directly back to your Netlify site.

### 2. Deploy Frontend on Netlify
1. Connect the repository to [Netlify](https://www.netlify.com/).
2. Set the **Publish Directory** to `static` (no build command needed).
3. In `static/index.html`, set your Render backend URL:
   ```javascript
   const API_BASE = window.API_BASE || "https://your-backend.onrender.com";
   ```
   *(Or inject `window.API_BASE = "https://your-backend.onrender.com"` in Netlify snippet settings).*
4. In local development, the app automatically falls back to `window.location.origin` / `localhost:8000`.

---

SplitSmart AI includes a ready-to-use `render.yaml` blueprint.

1. Push your repository to GitHub.
2. Go to [Render Dashboard](https://dashboard.render.com/) ➔ **New** ➔ **Blueprint**.
3. Connect your repository. Render will detect `render.yaml`.
4. Configure the environment variables (`GEMINI_API_KEY`, `PAYPAL_CLIENT_ID`, `PAYPAL_SECRET`, `BASE_URL`).
5. Click **Apply**.
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

---

## 📐 Honest Notes on Algorithms & Trade-offs

1. **Optimizer is Greedy (Heuristic)**:
   - The debt simplification algorithm in `app/optimizer.py` uses greedy creditor-debtor matching.
   - It matches the largest debtor with the largest creditor at each step.
   - **Why this choice**: Finding the absolute minimum number of transactions across arbitrary balances is equivalent to the NP-hard Subset Sum / Partition problem. The greedy algorithm executes in $O(N \log N)$, guarantees that every balance is zeroed, and produces at most $N-1$ transfers. We honestly describe it as a *reduced* transfer list rather than a guaranteed mathematical minimum.
2. **Single Merchant Account Sandbox**:
   - In this hackathon demo, all sandbox payment links route through the merchant account specified by `PAYPAL_CLIENT_ID`.
   - In a production peer-to-peer system, direct member-to-member routing would be implemented via **PayPal Payouts API** or **PayPal Complete Payments Multiparty**.

---

## 📜 License

MIT License. See [LICENSE](LICENSE) for details.
