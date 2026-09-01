# Architecture Decisions & Scenarios — WhatsApp Digital FTE

> A living decision log for the "Social Media Management Digital FTE" product.
> **Now (capstone, 2 days):** scoped WhatsApp-only slice.
> **Future:** full multi-platform (WhatsApp + Facebook + Instagram) managed Digital FTE that businesses subscribe to.
>
> Format for each entry: **Scenario → Decision → Why → Future note.**

---

## 1. Knowledge Base: Preload vs RAG

**Scenario:** A business gives us its info (fees, timings, services, FAQs). How does the agent access it?

**Decision (now):** **Preload** — inject the whole knowledge base into the agent's instruction/context.

**Why:** Data is small (a few paragraphs per business). RAG (embeddings + vector search) is overkill for small data — extra cost, extra setup, no benefit.

**Rule of thumb:**
- Small / stable data (a few pages) → **Preload**.
- Large / frequently-changing data (100+ pages, many businesses) → **RAG** (search returns only the relevant chunk, keeps context small and cheap).

**Future note:** When we onboard many businesses with large document sets, switch each business's knowledge base to **RAG** (one vector index per business / per tenant).

**Future enhancement — adaptive routing:** At onboarding, automatically measure the
knowledge size (token/character count) and pick the strategy per business:
- small (e.g. < ~4,000 tokens) → **preload**
- large → build a **RAG** index.
This makes the product scale without a human deciding preload-vs-RAG each time.

---

## 2. Platform Scope: WhatsApp-only vs Multi-platform

**Scenario:** The full vision manages WhatsApp + Facebook Pages + Instagram. What do we build first?

**Decision (now):** **WhatsApp only.**

**Why:**
- **WhatsApp Cloud API** is TOS-compliant and built for automation.
- **Facebook Pages** needs Meta app review (slower).
- **Instagram** DM/engagement automation is heavily restricted — bot-like behavior risks account bans.
- 2-day deadline: one channel done well > three channels half-broken.

**Future note:** Add Facebook (after app review) and Instagram (within Meta's messaging rules) as additional per-platform sub-agents behind the same Orchestrator. The architecture already supports this — just add sub-agents + tools.

---

## 3. NLP Handling

**Scenario:** Do we need a separate NLP layer (intent classification, entity extraction)?

**Decision:** **No.** The LLM (Gemini/GPT) that powers the agent *is* the NLP layer — it understands natural language, intent, and messy spelling natively.

**Why:** Modern LLMs make classic NLP pipelines unnecessary for this use case.

**Future note:** Only add structured NLP/analytics if we need deterministic reporting (e.g., categorizing message topics for dashboards).

---

## 4. Voice Handling

**Scenario:** What if a client sends a voice note or makes a call?

**Decision (now):** **Text only.**

**Why:**
- Voice notes (recorded audio) → possible via speech-to-text, but extra work — out of 2-day scope.
- Live phone calls → WhatsApp Cloud API does **not** let a bot answer calls; needs telephony (e.g., Twilio) + real-time speech. Separate, heavy build.

**Future note:** Phase 2 — add voice-note transcription (audio → text → agent). Phase 3 — telephony integration for live voice.

---

## 5. WhatsApp Connection: Sandbox vs Real API

**Scenario:** Real WhatsApp Cloud API needs Meta business verification, which can stall.

**Decision (now):** Use the **WhatsApp Cloud API test number (sandbox)** — issued instantly, no business verification, messages allowed to a few verified test numbers. Enough for the demo. Fallback: simulate the WhatsApp channel via `adk web` if even the sandbox stalls.

**Why:** Guarantees a working demo within the deadline. The capstone does not require a live public deployment.

**Future note:** Complete Meta Business verification for a production number and higher messaging limits.

---

## 6. Security: Human-in-the-Loop (HITL)

> **Status update (superseded in part, commit `733db6a`):** HITL is now **optional and OFF by
> default**. The shipped default is `REQUIRE_APPROVAL=false` → the AI books end-to-end and
> confirms the customer itself; set `REQUIRE_APPROVAL=true` to restore the owner-approval flow
> described below (`whatsapp_fte/webhook_agent.py:40`). The slot check and the duplicate-booking
> guardrail (#13) run in **both** modes, so booking safety is unchanged either way.

**Scenario:** Should the agent send/act on everything automatically?

**Decision:** **No.** Non-sensitive replies (fees, timings) go automatically; **sensitive actions** (booking, confirming, anything with a commitment) **pause for owner approval** (`request_confirmation` pattern).

**Why:** Safety + trust — this is our "Security features" course concept, and it prevents the agent from making costly mistakes on the business's behalf.

**Future note:** Make the sensitivity rules configurable per business (each owner sets what needs approval).

---

## 7. UI

**Scenario:** Do we build a custom UI?

**Decision:** **No custom UI.** Customer side = WhatsApp itself. Testing/demo side = ADK's built-in `adk web`.

**Why:** Saves time; WhatsApp is already the interface.

**Future note:** Build an owner dashboard (approvals, analytics, business onboarding) when productizing.

---

## 8. Business Model (from Agent Factory thesis)

**Scenario:** How is this sold?

**Decision:** **Digital FTE Subscription** — businesses hire an AI WhatsApp employee (~$500–2,000/month) instead of a human, running 24/7.

**Why:** Aligns with the "SaaS is dead → sell outcomes/workers, not licenses" thesis. Strong pitch for the "Agents for Business" track.

**Future note:** Add the other revenue models — Success Fee, License the Recipe, Skill Marketplace.

---

## 9. Conversation Memory: Session (short-term) vs Memory Bank (cross-session)

**Scenario:** A customer messages the WhatsApp agent. Should the agent remember (a) earlier messages in the same chat, and (b) past conversations from previous days?

**Decision (now):**
- **Short-term (same conversation)** → **YES.** Use ADK **Session** with `session_id = customer's phone number`, so each customer keeps their own running history. Required for multi-customer correctness.
- **Cross-session long-term (customer returns days later)** → **NOT now.** Deferred.

**Why:** Per-customer session context is essential and cheap (ADK handles it once we key sessions by phone number). Long-term memory (ADK **Memory Bank** / `VertexAiMemoryBankService`) adds infra + cost and isn't needed for the demo.

**Future note:** Add **Memory Bank** so the agent recalls a returning customer's name, past orders, and preferences across sessions — a big UX win for the productized Digital FTE.

---

## 10. Inbound Handling: Live Webhook vs `adk web` Demo (REAL PRODUCT)

**Scenario:** WhatsApp has **no polling API** — inbound customer messages arrive only via a **webhook** (Meta POSTs to a public HTTPS URL). How does the AI actually receive and reply to real WhatsApp messages, and how does booking approval work across two different phones (customer vs owner)?

**Decision:** Build a **real FastAPI webhook** (`whatsapp_webhook/`), not just an `adk web` demo — this is a launchable Digital FTE, not a mock.
- `GET /webhook` → Meta verification handshake (checks `WHATSAPP_VERIFY_TOKEN`, echoes the challenge).
- `POST /webhook` → inbound messages. Returns `200` immediately and processes in a **background task** (Meta retries slow responses), with **message-id dedupe**.
- **Routing:** if the sender is the **owner number** → treat as a booking approval reply; otherwise → **customer conversation** into the ADK agent.
- **Delivery model:** the webhook runs the agent as a pure **text-in → text-out brain** and delivers the reply itself via the shared `whatsapp_client`. So the live path does **not** spawn an MCP subprocess per message (fast, robust). The **MCP server stays** for the `adk web` demo and shares the exact same `whatsapp_client` send code — one delivery path everywhere.
- **Cross-channel HITL (the key upgrade):** booking is a sensitive action, so the customer agent calls `request_booking_approval`, which records a **pending booking** and messages the **owner's own WhatsApp** ("Reply YES/NO"). The owner approves from *their* phone; the webhook resolves the booking and notifies the customer. This **fixes the earlier `adk web` UX flaw** where the approval prompt wrongly appeared in the customer's chat.
- **Per-customer sessions:** `session_id = phone number`, so each customer keeps their own conversation history (see #9).

**Why:** Reflects how WhatsApp actually works and matches the product goal (launchable Digital FTE for social-media management, WhatsApp first). A real human still approves every commitment — genuine, cross-channel Human-in-the-Loop.

**Manual / infra steps:** run `uvicorn` + `ngrok http 8000` to get a public URL; paste it into Meta's WhatsApp webhook config with the verify token; regenerate the ~24h token before a live test; add both the customer and owner numbers as verified sandbox recipients.

**Future notes:**
- Verify Meta's `X-Hub-Signature-256` header (app secret) on `POST /webhook` for authenticity.
- Move the pending-booking store and sessions from in-memory to a **DB** for multi-worker production.
- Support media/voice, templates for messaging **outside** the 24-hour window, and multiple platforms beyond WhatsApp.

---

## 11. Business Type: Doctor Clinic "front-desk" FTE

**Scenario:** The sample business mixed doctor consultations *and* lab tests, which made the booking/availability model ambiguous.

**Decision:** Make it a **doctor clinic (consultations only)** — remove lab-test items. Booking = one doctor appointment slot (capacity 1 per slot).

**Why:** A single-resource (one doctor) schedule makes availability logic clean and realistic: a slot is either free or taken. Keeps the demo focused and internally consistent.

**Future note:** Multi-resource (several doctors/rooms), service-specific durations, and lab-test sample slots.

---

## 12. Booking Backend: Google Sheets (Availability + Bookings)

**Scenario:** Bookings were in-memory only — they vanished on restart (not a real record), and the AI had no idea which slots were free.

**Decision:** Use a **Google Sheet** as the shared operations backend, with two tabs:
- **`Availability`** — the doctor's weekly schedule (`Day, Open, Close, SlotMinutes`). The business fills this.
- **`Bookings`** — every confirmed appointment (`Date, Time, PatientName, Phone, Status, CreatedAt`). The booking team can open this sheet as their live dashboard.

**Flow:**
1. Customer requests a slot → AI tool `check_slot(date, time)` reads Availability minus already-booked → available or not.
2. **Available** → collect details → notify owner for approval (HITL) → on approval, **append to Bookings** + confirm the customer.
3. **Not available** → AI offers the next open slots (`suggest_alternatives`) → customer picks → approval → append + confirm.

**Why:** Makes bookings a **real, persistent, team-visible** record and gives the AI slot-awareness (no double-booking). Google APIs are fast/reliable from this network (unlike OpenAI here). Reinforces the "tools" concept; slot logic (`availability.py`) stays pure/unit-testable.

**Access/security:** service-account JSON key lives in `.secrets/` (off-limits to read/display); code uses it via a path in `.env` (`GOOGLE_SA_KEY_PATH`, `BOOKING_SHEET_ID`). Sheet is shared with the service-account email.

**Future note:** Reminders (reduce no-shows), reschedule/cancel flows, multi-doctor capacity, and moving off Sheets to a real DB/calendar (Google Calendar) at scale.

---

## 13. Guardrail: Duplicate-Booking Prevention via ADK Callback

**Scenario:** A customer might spam "book" repeatedly (by mistake or on purpose). Without a guard, the AI would notify the owner again and write duplicate rows — wasted work and a messy sheet.

**Decision:** Add a **`before_tool_callback`** on the booking tool (ADK's native guardrail mechanism). It blocks a new booking if the customer's phone already has an **active** booking, where active = a **pending** request OR a **confirmed booking dated today or later** (upcoming). Blocked → returns a "you already have a booking" message instead of running the tool.

**Date-based, not a manual flag:** past appointments do **not** count — once the appointment date passes, the block clears automatically and the customer can book again. This avoids "blocked forever" without needing a manual "arrived/attended" column, and it naturally handles no-shows (date passes → they can rebook).

**Why:** ADK doesn't have a feature literally named "Guardrails" (unlike OpenAI Agents SDK), but callbacks (`before_model_callback` / `before_tool_callback`) are the equivalent: return a dict to block, `None` to allow. This stops duplicate **side-effects** (owner notification, sheet double-entry). Adds a **new course concept** (guardrail via callback).

**Note:** The model call still happens, so it doesn't save the LLM token itself — it prevents the duplicate action.

**Future note:** An explicit "arrived/attendance" column, **reschedule / cancel** flows, no-show follow-up, a `before_model_callback` for spam/abuse filtering, and rate-limiting per phone number.

---

## 14. Future Onboarding: Multi-step Wizard (how a business gives context)

**Scenario:** Today the business context is **static** — one business in `business_profile.json`, seeded by the onboarding agent or by editing the file. That's fine for the capstone, but a real product needs businesses to onboard themselves.

**Decision (now):** Keep it **static / single-business** for the capstone. The "business → knowledge base" concept is already demonstrated (onboarding agent → profile → preload).

**Future design (documented, not built):** A **multi-step onboarding wizard** (like claude.ai's setup questions):
- Client logs in → selects **Business** → guided pages collect context (name, services, hours, FAQs), each page **skippable**.
- For WhatsApp specifically: **verify** the business is registered and that the provided number actually works for **inbound + outbound** (send a test, confirm webhook).
- At the end, all data is handed to the **orchestrator → onboarding agent**, which builds the knowledge base (**preload if small, RAG if large** — see #1).
- Needs deep design to cover all edge cases (missing data, invalid number, token setup, per-business isolation).

**Why:** Turns onboarding into a real self-serve product flow; out of scope for a 2-day capstone but the natural next step for the launchable Digital FTE.

---

## 15. Agent Architecture: Lean Single Agent (now) vs Orchestrator + Sub-agents (future)

**Scenario:** The project has two agent setups. `adk web` runs a multi-agent tree
(orchestrator → onboarding_agent + whatsapp_agent, with MCP tools and a single-chat
approval dialog). The live WhatsApp webhook runs a **lean single customer agent**
(`webhook_agent.py`: KB + `check_slot` + `create_booking_request`, cross-channel
owner approval, guardrail). Which is the real direction?

**Decision (now):** The **lean single agent** is what actually serves live WhatsApp
customers. It is deliberately minimal — one brain, in-process tools, the webhook
delivers replies and routes owner approvals. The orchestrator tree stays as the
`adk web` **concept demo** (shows multi-agent delegation + MCP visually) and is not
on the live path.

**Why lean now:** For a single business, single channel (WhatsApp), one focused agent
is faster to run (no per-message MCP subprocess, no extra delegation hops), easier to
reason about, and cheaper. The full orchestrator machinery isn't needed yet.

**Future (the productized Digital FTE):** Move to an **Orchestrator + specialized
sub-agents** design:
- **Onboarding agent** — self-serve business setup → knowledge base (see #14).
- **Per-platform agents** — WhatsApp, Facebook, Instagram behind one orchestrator (see #2).
- **Per-function agents** — e.g. scheduling, billing/payments, FAQ/support, escalation,
  each a specialist the orchestrator routes to.
- **Long-term memory** (Memory Bank, see #9) and **per-tenant isolation** so one
  deployment serves many businesses.

**Why orchestrator later:** As platforms, functions, and tenants multiply, a single
prompt can't hold it all. An orchestrator that delegates to focused specialists keeps
each agent small, testable, and independently improvable — the scalable shape for a
multi-platform, multi-business Digital FTE.

**Migration note:** the lean `webhook_agent` becomes (or is wrapped by) the WhatsApp
per-platform sub-agent under the future orchestrator; its booking tools/guardrail carry
over as-is.
