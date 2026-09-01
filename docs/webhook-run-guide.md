# Live Webhook — Run & Test Guide

How to take the WhatsApp Digital FTE live on a real phone. Everything is already
built and tested offline; these are the run/connect steps.

Two phones are involved:
- **Customer** = your personal WhatsApp.
- **Owner / booking team** = a second WhatsApp number (approves bookings).

Both must be added as **verified recipients** in the WhatsApp sandbox.

---

## 0. One-time prerequisites

1. **Fresh WhatsApp token** — Meta's temporary token expires ~every 24h.
   Meta Developer → your app → WhatsApp → **API Setup** → copy the token.
2. **Add `WHATSAPP_OWNER_NUMBER`** to `whatsapp_fte/.env` (the second/owner number,
   international format, e.g. `9231XXXXXXXX`). *(Variable name only — put your own value.)*
3. **Verify both numbers** as recipients in WhatsApp → API Setup → "To" list.
4. **ngrok authtoken** (already installed). If not yet configured:
   `ngrok config add-authtoken <YOUR_TOKEN>` (free token from dashboard.ngrok.com).

---

## 1. Start the webhook server

From the project root (`whatsapp_fte_agent/`):

```bash
/mnt/e/kaggle/.venv/bin/uvicorn whatsapp_webhook.main:app --port 8000
```

Leave it running. Health check: open `http://localhost:8000/` → `{"status":"up"}`.

## 2. Expose it publicly with ngrok

In a **second terminal**:

```bash
ngrok http 8000
```

Copy the `https://....ngrok-free.app` **Forwarding** URL.

## 3. Connect the webhook in Meta

Meta Developer → your app → WhatsApp → **Configuration** → Webhook → **Edit**:
- **Callback URL:** `https://....ngrok-free.app/webhook`
- **Verify token:** the exact value of `WHATSAPP_VERIFY_TOKEN` in your `.env`.
- Click **Verify and save** → Meta calls `GET /webhook`; you should see a request
  in the ngrok/uvicorn logs and a green tick.
- Under **Webhook fields**, subscribe to **messages**.

## 4. Test it live

> **Which flow runs depends on `REQUIRE_APPROVAL`** (`whatsapp_fte/webhook_agent.py:40`).
> The default is **`false` → auto-confirm**: the AI validates the slot, writes the confirmed
> booking to the sheet, and confirms the customer itself — the owner phone is not involved.
> The owner-approval steps below apply only when `REQUIRE_APPROVAL=true`.

### 4a. Default — auto-confirm (`REQUIRE_APPROVAL` unset or `false`)

1. From your **customer** phone, message the business number:
   *"What are your timings?"* → AI replies from the knowledge base.
2. Send: *"Book me an appointment tomorrow 5 PM, my name is Ali."*
   → AI collects name + consultation type, shows a summary, asks *"Shall I book it?"*
3. Reply **`yes`** → AI checks the slot, appends the row to the **Bookings** sheet, and
   replies `✅ … CONFIRMED …`. No second phone needed.

### 4b. Optional HITL (`REQUIRE_APPROVAL=true`, then restart uvicorn)

1. Same as above, but after the customer says `yes` the AI replies that it's confirming
   with the team.
   → The **owner** phone gets: `🔔 New booking request #1 … Reply YES 1 / NO 1`.
2. From the **owner** phone reply **`YES 1`**.
   → The **customer** phone gets: `✅ … appointment … confirmed`.
   (Reply `NO 1` instead → customer is offered the next open slots.)

That's the full loop: real inbound → AI brain → (optional cross-channel human approval) → real reply.

---

## Notes / gotchas

- **24-hour window:** free-form replies only work if the customer messaged first
  within the last 24h. The owner must also have messaged the business once so we can
  message them (or pre-open that window before the demo).
- **Token expiry:** if replies stop with a 401, regenerate the token in `.env` and
  restart uvicorn.
- **ngrok URL changes** each restart (free tier) — re-paste it into Meta if you restart ngrok.
- **Single process:** sessions + pending bookings are in-memory; restarting uvicorn clears them.
