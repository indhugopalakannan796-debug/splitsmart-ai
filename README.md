# SplitSmart AI

Snap the bill. AI splits it fairly, minimizes transfers, and collects the money through PayPal (Sandbox).

**Live demo:** https://splitsmart-ai-542t.onrender.com

## What it does
1. Upload a receipt photo. Gemini extracts items, quantities, prices, tax and total, and warns about mismatches instead of silently fixing them.
2. Describe who had what in plain language, or click the item-by-person matrix. The AI converts the sentence into assignments.
3. A deterministic engine computes each person's share: shared items are split only among the people who took part, tax/GST is distributed in proportion to each person's subtotal, and shares always sum exactly to the bill.
4. Across several expenses with different payers, an optimizer reduces the number of transfers needed (8 to 4 in our demo).
5. Each transfer gets a PayPal checkout link. The app tracks pending/paid status, and the AI drafts friendly, firm or humorous reminders.

## How we use PayPal (Sandbox)
- **PayPal Orders v2 REST API**: one order (intent CAPTURE) is created per settlement transfer for the exact amount owed.
- **PayPal checkout approval**: the payer approves on the PayPal sandbox page and is redirected to `/paypal/return`.
- **Capture**: the backend captures the order and marks the transfer as paid.
- **Order status lookup**: the "Refresh status" button and a 5-second polling loop re-check pending orders.
- **Sandbox accounts**: one business (receiver) and personal (buyer) accounts, with the app Client ID and Secret supplied through environment variables.

## How we use AI
- **Google Gemini** (model set by `GEMINI_MODEL`, default `gemini-3.5-flash-lite`, via the `google-genai` SDK):
  - reads receipt photos into structured JSON (items, tax, total),
  - parses plain-language sentences into item assignments,
  - drafts payment reminders in different tones.
- **The AI only interprets.** All money math runs in deterministic Python using integer minor units (largest-remainder rounding), and the shares must equal the bill total. The optimizer is a greedy creditor-debtor matcher.

## Other tools and technologies
FastAPI, Python, SQLite, Pydantic, httpx, Tailwind CSS, vanilla JavaScript, pytest. Built with the help of Antigravity (AI coding IDE) and Claude (planning and debugging).

## Sponsor integration
- **Render**: the whole app (FastAPI backend and static UI) runs as one Render web service, auto-deployed from this GitHub repo (`render.yaml`), with all secrets stored as Render environment variables.

## Setup and run locally
Prerequisites: Python 3.11+, a PayPal developer account, a Gemini API key.

```bash
git clone https://github.com/indhugopalakannan796-debug/splitsmart-ai.git
cd splitsmart-ai
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # Windows: copy .env.example .env
```

1. **PayPal Sandbox**: at developer.paypal.com open the Dashboard, go to Sandbox accounts (use a Business and a Personal account), then Apps & Credentials, make sure *Sandbox* is selected, create an app and copy the Client ID and Secret.
2. **Gemini**: create an API key in Google AI Studio.
3. Fill in `.env`:

| Variable | Meaning |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio key |
| `GEMINI_MODEL` | Gemini model ID (default `gemini-3.5-flash-lite`) |
| `PAYPAL_CLIENT_ID`, `PAYPAL_SECRET` | PayPal Sandbox app credentials |
| `PAYPAL_CURRENCY` | Currency for PayPal orders (e.g. `USD`) |
| `BASE_URL` | Public URL of the app, used for PayPal return URLs (`http://localhost:8000` locally) |
| `MOCK_AI`, `MOCK_PAYPAL` | `true` uses built-in sample data / a simulated checkout, for offline development only |

Run:
```bash
uvicorn app.main:app --reload --port 8000
```
Open http://localhost:8000. To pay in the sandbox, log in to the PayPal checkout page with a **sandbox personal account** (never a real PayPal account).

Tests:
```bash
pytest
```

## Mock modes
`MOCK_AI` and `MOCK_PAYPAL` exist so the UI can be developed offline. The hosted demo is meant to run with both set to `false`.

## Limitations
- Payments use the PayPal Sandbox only. No real money moves.
- The optimizer is greedy: it reduces the number of transfers but does not guarantee the theoretical minimum.
- SQLite data is reset when the free-tier Render instance restarts.
- AI output is shown for review and can be edited before any payment is created.

## License
MIT. See [LICENSE](LICENSE).
