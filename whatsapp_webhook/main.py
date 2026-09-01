"""Live WhatsApp webhook — the real product entry point.

This makes the Digital FTE respond on real WhatsApp:
  GET  /webhook  -> Meta verification handshake (uses WHATSAPP_VERIFY_TOKEN).
  POST /webhook  -> inbound messages. Routing:
                      - sender == owner  -> booking approval reply (YES/NO) -> confirm customer
                      - otherwise        -> customer message -> ADK agent -> reply on WhatsApp

Run locally:
    uvicorn whatsapp_webhook.main:app --port 8000
    ngrok http 8000        # gives a public https URL for Meta's webhook config

Env used (names only; values live in whatsapp_fte/.env):
    WHATSAPP_VERIFY_TOKEN, WHATSAPP_OWNER_NUMBER (+ the client's ACCESS_TOKEN / PHONE_NUMBER_ID)
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT / _HEADERS  (optional — production tracing)
"""

import contextlib
import os
import re
import sys

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Query, Request, Response

# Make the whatsapp_fte package importable and load the single .env.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
load_dotenv(os.path.join(_PROJECT_ROOT, "whatsapp_fte", ".env"))


# ---------------------------------------------------------------------------
# Production tracing (OpenTelemetry) — optional, opt-in, fail-safe
# ---------------------------------------------------------------------------
# ADK already instruments its Runner: it opens `invocation` -> `call_llm` ->
# `execute_tool` spans carrying GenAI semantic-convention attributes (model,
# input/output messages, tool definitions, token usage). Those spans exist on the
# live webhook path too, but OTel drops them while no TracerProvider is registered
# — which is why production has had no traces so far.
#
# `maybe_set_otel_providers()` registers one from the standard OTEL_* env vars.
# We deliberately use the TRACES-specific endpoint variable: the generic
# OTEL_EXPORTER_OTLP_ENDPOINT would also switch on the metrics and logs exporters,
# which our backend does not take yet and which would then log errors on a loop.
def _setup_tracing() -> bool:
    """Register an OTel TracerProvider if an OTLP traces endpoint is configured."""
    if not os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        return False  # not configured -> behave exactly as before
    try:
        from google.adk.telemetry.setup import maybe_set_otel_providers

        maybe_set_otel_providers()
        return True
    except Exception as e:  # never let telemetry take the webhook down
        print(f"[telemetry] tracing setup FAILED, continuing without it: {e}", flush=True)
        return False


_TRACING_ENABLED = _setup_tracing()
print(f"[telemetry] OTel tracing {'ENABLED' if _TRACING_ENABLED else 'disabled'}", flush=True)


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield
    # Spans leave in batches, so flush before the process exits — otherwise the
    # last conversation's trace is lost whenever the host restarts or sleeps.
    if _TRACING_ENABLED:
        try:
            from opentelemetry import trace

            provider = trace.get_tracer_provider()
            if hasattr(provider, "shutdown"):
                provider.shutdown()
                print("[telemetry] spans flushed on shutdown", flush=True)
        except Exception as e:
            print(f"[telemetry] flush on shutdown failed: {e}", flush=True)


from whatsapp_fte import availability, booking_store, sheets_client, whatsapp_client  # noqa: E402
from whatsapp_webhook.agent_bridge import get_reply  # noqa: E402

app = FastAPI(title="WhatsApp Digital FTE — Webhook", lifespan=_lifespan)

# Message ids we've already handled (Meta can redeliver). Simple in-memory dedupe.
_seen_ids: set[str] = set()


def _owner_number() -> str:
    return (os.getenv("WHATSAPP_OWNER_NUMBER") or "").lstrip("+")


# ---------------------------------------------------------------------------
# GET /webhook  — Meta verification handshake
# ---------------------------------------------------------------------------
@app.get("/webhook")
async def verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        # Meta expects the raw challenge echoed back as plain text.
        return Response(content=hub_challenge or "", media_type="text/plain")
    return Response(content="Verification failed", status_code=403)


# ---------------------------------------------------------------------------
# POST /webhook  — inbound messages
# ---------------------------------------------------------------------------
@app.post("/webhook")
async def receive(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()

    # WhatsApp nests the payload; status callbacks have no "messages" -> ignore.
    try:
        value = data["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return {"status": "ignored"}

    messages = value.get("messages")
    if not messages:
        return {"status": "ignored"}  # delivery/read status callback, etc.

    msg = messages[0]
    msg_id = msg.get("id", "")
    if msg_id in _seen_ids:
        return {"status": "duplicate"}
    _seen_ids.add(msg_id)

    sender = msg.get("from", "")
    if msg.get("type") != "text":
        whatsapp_client.send_text(sender, "Sorry, I can only read text messages right now.")
        return {"status": "ok"}

    text = msg["text"]["body"]
    contacts = value.get("contacts", [{}])
    name = contacts[0].get("profile", {}).get("name", "") if contacts else ""

    # Return 200 immediately (Meta retries on slow responses); process in the background.
    background_tasks.add_task(_process, sender, text, name)
    return {"status": "received"}


async def _process(sender: str, text: str, name: str):
    """Route an inbound message: owner approval vs customer conversation."""
    import time
    import traceback

    print(f"[process] incoming from {sender}: {text!r}", flush=True)
    owner = _owner_number()
    if owner and sender.lstrip("+") == owner:
        print("[process] -> owner approval reply", flush=True)
        _handle_owner_reply(text)
        return

    # Customer conversation -> agent brain -> deliver reply.
    try:
        t0 = time.time()
        reply = await get_reply(sender, text)
        print(f"[process] agent reply in {time.time()-t0:.1f}s: {reply!r}", flush=True)
        t1 = time.time()
        result = whatsapp_client.send_text(sender, reply)
        print(f"[process] send result in {time.time()-t1:.1f}s: {result}", flush=True)
    except Exception:
        print("[process] ERROR while handling customer message:", flush=True)
        traceback.print_exc()


def _handle_owner_reply(text: str):
    """Parse the owner's YES/NO [id] and resolve the pending booking."""
    lowered = text.strip().lower()
    approve = lowered.startswith("yes") or lowered.startswith("approve")
    reject = lowered.startswith("no") or lowered.startswith("reject")
    if not (approve or reject):
        return  # not an approval message; ignore

    m = re.search(r"(\d+)", text)
    bid = m.group(1) if m else booking_store.latest_pending_id()
    if not bid:
        return

    booking = booking_store.resolve(bid, approved=approve)
    owner = os.getenv("WHATSAPP_OWNER_NUMBER")
    if not booking:
        print(f"[approval] no pending booking #{bid}", flush=True)
        if owner:
            whatsapp_client.send_text(owner, f"No pending booking #{bid} found.")
        return

    decision = "approved" if approve else "rejected"
    print(f"[approval] booking #{bid} {decision} for {booking['customer_phone']}", flush=True)

    if approve:
        # Persist the confirmed booking to the Google Sheet (the team's dashboard).
        try:
            sheets_client.append_booking(
                booking["date"], booking["time"],
                booking["customer_name"], booking["customer_phone"], "confirmed",
                service=booking.get("service", ""),
            )
            print("[approval] written to Bookings sheet", flush=True)
        except Exception as e:
            print(f"[approval] sheet write FAILED: {e}", flush=True)

        svc = booking.get("service", "")
        svc_line = f" ({svc})" if svc else ""
        r = whatsapp_client.send_text(
            booking["customer_phone"],
            f"✅ Good news! Your appointment{svc_line} for {booking['appointment_time']} is confirmed. See you then!",
        )
        print(f"[approval] customer confirm send: {r}", flush=True)
        if owner:
            whatsapp_client.send_text(owner, f"Booking #{bid} approved ✅ — added to sheet, customer notified.")
    else:
        alt_text = _alternatives_text(booking["date"])
        body = f"Sorry, {booking['appointment_time']} isn't available. "
        body += (alt_text + "\nReply with a time that suits you and I'll book it."
                 if alt_text else "Please share another day/time and we'll check for you.")
        r = whatsapp_client.send_text(booking["customer_phone"], body)
        print(f"[approval] customer reject+alternatives send: {r}", flush=True)
        if owner:
            whatsapp_client.send_text(owner, f"Booking #{bid} rejected ❌ — customer offered other slots.")


def _alternatives_text(from_date: str) -> str:
    """Build an organised list of the next open slots from the Sheet, grouped by date."""
    try:
        avail = sheets_client.get_availability()
        bookings = sheets_client.get_bookings()
        alts = availability.suggest_alternatives(from_date, avail, bookings, max_slots=6)
    except Exception as e:
        print(f"[approval] alternatives lookup failed: {e}", flush=True)
        return ""
    if not alts:
        return ""
    by_date: dict[str, list[str]] = {}
    for d, t in alts:
        by_date.setdefault(d, []).append(t)
    lines = [f"📅 {d}: " + ", ".join(times) for d, times in by_date.items()]
    return "Here are the next available slots:\n" + "\n".join(lines)


@app.get("/")
async def health():
    return {"service": "WhatsApp Digital FTE webhook", "status": "up"}
