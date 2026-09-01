# Voice / Call Handling — v2 Roadmap & Design Spec

**Status:** Planned for v2 (AFTER the capstone). The v1 product is WhatsApp **text** only.
**Goal:** Let patients who prefer *calling* (elderly, non-texters, urgent) reach the clinic 24/7,
using the SAME agent brain, tools, guardrail, and human-in-the-loop (HITL) approval as WhatsApp.

> Design principle: **Voice is just another channel.** One brain (`build_customer_agent()`),
> many channels (WhatsApp text ➜ WhatsApp/phone voice). Don't fork the logic.

---

## 1. Verified tech stack (July 2026)

| Layer | Choice | Notes (verified) |
|---|---|---|
| Telephony / call path | **Twilio Voice + WhatsApp Business Calling** | GA since 2025-07-15. WhatsApp calls are **VoIP-only** (cannot bridge to PSTN numbers). |
| Voice ↔ text (STT/TTS) + orchestration | **Twilio ConversationRelay** | Bring-your-own-LLM. Latency verified: median <0.5s, p95 <0.725s. **$0.07/min**. |
| Brain | **Our existing ADK `build_customer_agent()`** via websocket | Reuses tools, duplicate guardrail, HITL, Google Sheets. |
| Session state | **`DatabaseSessionService` (REQUIRED for voice)** | A live call can't survive Render free-tier sleep / in-memory loss. |

**Speed-first alternative (less control, brain fragments):** Vapi (~$0.13–0.31/min) or Retell
(~$0.11–0.15/min) — managed STT+LLM+TTS; expose our booking as a function they call.

### Cost summary
- **Build/test:** effectively free — Twilio new-account **$15 trial credit**.
- **Production (per minute):** ConversationRelay $0.07/min + WhatsApp Business Calling connectivity
  (Twilio channel fee + Meta per-minute fee, varies by country — **check PK rate**) + OpenAI tokens.

### Gotcha we already hit (enabling WhatsApp calling)
Calling does **not** appear by default on a Cloud API test number. To enable:
1. Phone number status must be **Verified** in WhatsApp Manager (if *Unverified*, the **Calls tab is hidden**).
2. Number must be on **Cloud API** (not the WhatsApp Business app).
3. **Subscribe the app to the `calls` webhook field** (it's an API/webhook config, not just a UI button).
Test numbers *can* test Calling API (no 2000-conversation limit needed) once enabled.

---

## 2. Architecture (target)

```
Caller (WhatsApp voice / phone)
        │  VoIP
        ▼
   Twilio Voice ──► ConversationRelay  (STT + TTS + streaming)
        │  websocket (text in / text out)
        ▼
   voice_bridge  ──►  build_customer_agent()   ← SAME brain as whatsapp_webhook/
        │                    │ tools: check_my_appointment, check_slot, create_booking_request
        │                    │ guardrail: _block_duplicate_booking
        ▼                    ▼
   DatabaseSessionService   Google Sheets (Availability / Bookings)  +  owner HITL approval
```

New code = one `voice_bridge` (websocket ⇄ agent), mirroring `whatsapp_webhook/agent_bridge.py`.
Everything else is reused.

---

## 3. HITL on a call (same honesty as WhatsApp)
- **Automated:** greet, answer KB, check slot, create *pending* booking, **read back date/time**, send WhatsApp/SMS summary.
- **Needs doctor approval:** every **confirmed** booking. Caller hears *"team will confirm shortly, you'll get a WhatsApp"* — **not** an instant confirmation.
- **Forbidden to AI:** medical advice/diagnosis/dosage, confirming without the doctor, quoting unknown prices, handling emergencies itself.
- **Human unavailable:** booking stays `pending` → timeout → auto status message.

---

## 4. Guardrails the voice agent MUST enforce
1. **Medical advice → refuse + redirect to doctor** (never diagnose/prescribe).
2. **Emergency keywords (chest pain, bleeding, unconscious…) → immediate "call 1122 / go to ER", NO booking.**
3. **Recording consent line** at call start ("this call may be recorded").
4. **Read-back confirmation** of name/date/time/phone before any booking action (STT can mishear Urdu-English).
5. **Answer only from KB** — refuse unknown fees/hours instead of inventing.
6. **Max call duration + per-minute cost cap.**

---

## 5. Top edge cases (build tests for these first)
Accent/Urdu STT errors · medical-advice requests · emergencies · dead-air latency · call drops mid-booking ·
double-booking across channels · wrong phone/date heard · caller demands a human · spam calls · consent/legal.

---

## 6. Open questions to answer BEFORE coding (ranked by risk)
1. 🔴 Do target clinics have real callers who **won't** use WhatsApp text? (else voice is redundant)
2. 🔴 Legal: call recording/consent + health-data handling rules in Pakistan.
3. 🔴 STT accuracy on **Roman-Urdu / Urdu-English** — test before committing.
4. 🟠 Managed (Vapi/Retell) vs ConversationRelay + our agent — priority: speed vs one-brain control.
5. 🟠 WhatsApp-call-only vs also a PSTN number.
6. 🟡 Can PK clinics afford per-minute voice pricing?

## 7. Kill criteria
Abandon/pivot if: clinics won't trust AI *speaking* to patients · per-minute cost > willingness to pay ·
any medical/emergency mishandling in pilot · Urdu-English STT accuracy too low to trust bookings.

## 8. Time estimate (honest)
- Basic demo (WhatsApp call → agent talks → pending booking): **~2–3 days**.
- Production-ready (all guardrails + Urdu STT tuning + session persistence + consent): **~1–2 weeks**.
- Prerequisite: implement `DatabaseSessionService` first.

## 9. Definition of done (v2 MVP)
Inbound call answered → KB Q&A → book (pending) → read-back → WhatsApp/SMS summary → medical+emergency
guardrails → consent line. **Out of scope:** outbound calls, payments on call, languages beyond Urdu/English.

---

### Sources
- Twilio — WhatsApp Business Calling (docs / GA announcement)
- Twilio — ConversationRelay & Core Latency guide; Twilio Pricing
- APIScout — Realtime Voice AI APIs Compared 2026; Vapi/Retell pricing (Ainora, Retell blog)
- Meta for Developers — Cloud API Calling (test number enablement)
