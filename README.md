# 🤖 persona-agent

An open-source, configurable AI agent that talks to people **on your behalf**. Out of the box it is a *personal representative*: it answers questions about you, qualifies recruiters and clients, books meetings, and pings you when it needs your input. Edit one file (`agent.yaml`) and it becomes a support bot, a sales assistant, or anything else that answers from your documents and captures leads.

Two small config files define everything, with no code changes needed:

- **`.env`** says *who* the agent speaks for (a person or a business) plus your keys.
- **`agent.yaml`** says *what* it does: purpose, conversation workflows, lead forms, which capabilities are on, and the UI copy and colors.

## What it does

| Capability | How |
| :--- | :--- |
| Answers questions from your documents (resume, help docs, product docs) | RAG over `knowledge/` using ChromaDB + OpenAI embeddings |
| Captures leads with fields **you define** (default: recruiter and project forms) | `lead_forms` in `agent.yaml`; each one logs a lead and notifies you |
| Books meetings with a Google Meet link | Google Calendar (optional) |
| Asks **you** when it doesn't know the answer | Telegram, waits ~60s for your reply (optional) |
| Phone alerts for every new lead | Pushover (optional) |
| Stores leads and chat transcripts | Firestore (optional; otherwise printed to the console) |

Only `USER_NAME` and an **OpenAI API key** are required. Every other integration turns on automatically when you add its credentials.

---

## Quick start (run locally)

You need Python 3.11+ and an [OpenAI API key](https://platform.openai.com/api-keys).

```bash
git clone https://github.com/<your-username>/persona-agent.git
cd persona-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

**1. Tell it who it represents** — edit `.env`. Only `USER_NAME` and `OPENAI_API_KEY` are required; the app refuses to start without them, and leaves out anything else you don't fill in:

```env
USER_NAME="Your Full Name"          # a person or a business, e.g. "Acme Support"
USER_TITLE="Your Professional Title"
USER_LOCATION="City, Country"
USER_EMAIL="you@example.com"
USER_SKILLS="Python, React, Cloud Architecture"
USER_CALENDAR_URL=""      # optional booking link, e.g. https://cal.com/you
USER_LINKEDIN_URL=""      # optional
USER_GITHUB_URL=""        # optional
OPENAI_API_KEY="sk-..."
```

**2. Choose what it does** — the default `agent.yaml` is a personal professional representative (recruiters, project inquiries, visitors). Keep it, edit it, or start from an example. See [Adapt it to your use case](#adapt-it-to-your-use-case).

**3. Write your bio** — replace the sample text in `knowledge/summary.txt` with a few paragraphs about you (or your business): who you are, what you offer. It is shown in the sidebar and given to the agent.

**4. Add your documents** — drop your resume (PDF), project write-ups (`.md`) or notes (`.txt`) into `knowledge/`. These files are git-ignored (only the sample `summary.txt` is tracked), so your resume never lands in a public repo by accident. The agent builds its search index automatically the first time it starts. After changing files in `knowledge/`, rebuild it:

```bash
python ingest.py
```

**5. Run it**

```bash
python app.py
```

Open <http://localhost:7860>. Done. 🎉

> `knowledge/summary.txt` ships with a sample bio so the page isn't empty. Replace it with your own.

---

## Adapt it to your use case

`agent.yaml` is the only file you edit to change what the agent is. The shipped one is the "personal representative"; `examples/` has two more:

```bash
AGENT_CONFIG=examples/support-bot.yaml python app.py       # customer-support assistant
AGENT_CONFIG=examples/sales-assistant.yaml python app.py   # sales / lead qualification
```

(For a support bot, set `USER_NAME="Acme Support"` and put your help docs in `knowledge/`.)

| Section | What it controls |
| :--- | :--- |
| `agent` | Name, tagline, badge, hero text, greeting, accent color (`theme_color`) |
| `purpose`, `tone` | Who the agent is and how it speaks (goes into the system prompt) |
| `workflows` | Conversation scenarios. Each becomes a prompt section, a sidebar card and a welcome bullet |
| `suggestions` | Quick-reply chips under the welcome message |
| `features` | Switch built-ins on or off: `knowledge_base`, `contact_capture`, `scheduling`, `escalation` |
| `lead_forms` | Your own lead-capture tools: name, description, fields (required, choices, minimum length), saved to their own collection |

Example: add a form for a restaurant-booking agent, with no Python at all:

```yaml
lead_forms:
  - name: request_reservation
    title: "🍽️ Reservation Request"
    description: Record a table request once you have a date, party size and contact.
    collection: reservations
    success_message: Request received; we will confirm by email.
    fields:
      - {name: guest_name, required: true}
      - {name: party_size, required: true}
      - {name: date_time, required: true}
      - {name: dietary_notes}
      - {name: seating, choices: [Indoor, Outdoor, No preference], default: No preference}
```

**Lead form reference**

| Form key | Meaning |
| :--- | :--- |
| `name` | Tool name the model calls (lowercase, digits, underscores) |
| `description` | Tells the model *when* to call it |
| `collection` | Firestore collection the leads are saved to |
| `title` | Heading of the push notification (you may start it with an emoji) |
| `success_message` | What the model may tell the visitor after a successful save |
| `require_any` | Field names; at least one must contain real information |
| `fields` | The questions to capture (below) |

| Field key | Meaning |
| :--- | :--- |
| `name` | Field name (lowercase, digits, underscores) |
| `description` | Optional hint for the model |
| `required` / `min_chars` | The save is refused (and the model asked to collect it) if missing or too short |
| `choices` / `default` | Restrict the value to a list; `default` is used when not given |

Text in `agent.yaml` can use `{user_name}`, `{user_title}`, `{user_location}`, `{user_email}` and `{agent_name}`. The file is validated at startup, so a typo (unknown key, bad color, duplicate tool name, a field name that doesn't exist) stops the app with a message saying exactly what to fix. Mention a form's tool name in a workflow's `instructions` so the model knows when to call it. Forms get the same safety behavior as the built-in leads (honest `OK:` / `NOT_SAVED:` results, per-visitor limits). OpenAI is the only model provider today.

---

## Optional integrations

Add these to `.env` only if you want them.

<details>
<summary><b>Telegram — let the agent ask you questions live</b></summary>

1. In Telegram, message `@BotFather`, run `/newbot`, and copy the token to `TELEGRAM_BOT_TOKEN`.
2. Message `@userinfobot` to get your numeric ID and put it in `TELEGRAM_CHAT_ID`.
3. Send any message to your new bot once so it can reach you.

When a visitor asks something the agent can't answer, it messages you. **Swipe-reply** to that message and your answer appears in the web chat (a plain message also works when only one visitor is waiting). Only messages from your `TELEGRAM_CHAT_ID` are accepted. Telegram allows one listener per bot, so run a **single instance** (the deploy command below sets `--max-instances 1`).
</details>

<details>
<summary><b>Pushover — phone alerts for leads</b></summary>

Install the [Pushover](https://pushover.net) app, then set `PUSHOVER_USER` (your user key) and `PUSHOVER_TOKEN` (an application token).
</details>

<details>
<summary><b>Firestore — save leads and transcripts</b></summary>

1. In the [Firebase Console](https://console.firebase.google.com) create a project and a Firestore database.
2. Project settings → Service accounts → **Generate new private key**.
3. Save it as `serviceAccountKey.json` in the project root, **or** paste the JSON (single line) into `FIREBASE_CREDENTIALS_JSON`.

Without this, leads are printed to the console and nothing is stored.
</details>

<details>
<summary><b>Google Calendar — automatic meeting booking with Meet links</b></summary>

1. In Google Cloud Console enable the **Google Calendar API**.
2. Create a service account and download its JSON key. Save it as `calendar_service_account.json` in the project root, **or** paste it into `GOOGLE_CALENDAR_CREDENTIALS_JSON`.
3. In Google Calendar → Settings → *Share with specific people*, add the service account's email with **Make changes to events**.
4. Set `GOOGLE_CALENDAR_ID` (your calendar's email, or `primary`) and `MEETING_DEFAULT_TIMEZONE` (e.g. `America/New_York`).

Auto-generated Meet links need a Google Workspace calendar; on a personal Gmail calendar the event is still created, just without a Meet link. For Workspace domain-wide delegation, also set `GOOGLE_CALENDAR_OWNER_EMAIL`.
</details>

---

## Deploy it (Google Cloud Run)

The included `Dockerfile` runs anywhere Docker runs. These steps use [Google Cloud Run](https://cloud.google.com/run), which has a free tier.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

Build and deploy in one step from the project folder (replace the values with your own; add any optional variables from `.env` the same way). If gcloud asks to enable APIs or create an Artifact Registry repository, answer yes:

```bash
gcloud run deploy persona-agent \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --max-instances 1 \
  --set-env-vars "USER_NAME=Your Full Name,USER_TITLE=Your Title,USER_EMAIL=you@example.com,OPENAI_API_KEY=sk-..."
```

To deploy a different agent definition, add `AGENT_CONFIG=examples/support-bot.yaml` (or your own file in the project folder) to `--set-env-vars`, separated by a comma.

Cloud Run prints your public URL — that's your live agent. Your `knowledge/` files are uploaded with the build (`.gcloudignore` makes sure of that, even though they are git-ignored) and the search index is rebuilt in the background each time the container starts, so the site is up immediately and answers from documents become available after a short while.

> **Keep secrets out of the image.** `.env` and key files are excluded by `.dockerignore` and `.gcloudignore`. Pass credentials as env vars (above), or better, store them in [Secret Manager](https://cloud.google.com/run/docs/configuring/services/secrets).

**Updating:** change your files, then re-run the same `gcloud run deploy` command.

### Optional: custom domain / CDN with Firebase Hosting

`firebase.json` is preconfigured to forward all traffic to a Cloud Run service named `persona-agent` in `us-central1` (edit it if you used different values).

```bash
npm install -g firebase-tools
firebase login
firebase use YOUR_PROJECT_ID
firebase deploy --only hosting
```

---

## How handoffs fail safely

The agent never tells a visitor something was saved or forwarded unless it really was. Every tool returns an explicit outcome the model must follow:

| Result | Meaning | What the visitor is told |
| :--- | :--- | :--- |
| `OK:` | Saved to Firestore and/or the Pushover alert went out | Confirmation |
| `LOGGED_LOCALLY:` | No database or alerts configured, so only the server log has it | "Noted", with no promise of a reply, plus your booking link or email |
| `NOT_SAVED:` | Storage and alerts failed, **or** required info is missing (invalid email, empty lead, one-line project) | The agent asks for the missing detail or points to another way to reach you |
| `EXPIRED:` | Telegram delivered the question but you didn't reply within ~1 minute | Apology, offer to take their email; no promised reply time |

Telegram escalations are tracked in the Firestore `escalations` collection through `pending → delivered → resolved | expired`, or `failed` if Telegram never confirmed delivery, each with a timestamp. A reply sent after the 1-minute window is stored on the escalation (`late: true`) but is not shown in the chat.

## ⚠️ Before you go public

- **Cost:** anyone who finds the URL can chat, and every message uses your OpenAI credits. Built-in guards limit message length, history sent to the model, and messages per visitor session and IP (see section 9 of `.env.example`), but the real safety net is a **monthly spend limit in your OpenAI dashboard**. Set one.
- **Leads need a destination:** without Firestore or Pushover, leads are only written to the server log and you are *not* notified. The startup log warns you about this.
- **Calendar:** visitors can only book weekdays 09:00–18:00 (your `MEETING_DEFAULT_TIMEZONE`), 15–60 minutes, within 60 days, in free slots, with a few bookings per visitor and per hour. Adjust in `.env` (section 10).
- **Privacy:** visitors' names, emails and chat transcripts are stored in your Firestore if you enable it, messages are processed by OpenAI, and lead details are printed to your logs when no database is set up. The page footer shows a notice (change it with `PRIVACY_NOTICE`). Follow the privacy rules that apply to you.
- **Never commit** `.env`, `serviceAccountKey.json` or `calendar_service_account.json` (already in `.gitignore`).

---

## Project layout

```
app.py          Gradio app, chat loop, per-visitor limits
config.py       Loads .env (who) and agent.yaml (what), shared constants
agent.yaml      The agent's purpose, workflows, lead forms, features and UI copy
agent_config.py  Loads and validates agent.yaml
examples/       Ready-made agent.yaml files (support bot, sales assistant)
context.py      System prompt built from your profile and agent.yaml
tools.py        Agent tools: leads, knowledge search, calendar, escalation
telegram_hitl.py  Shared Telegram poller for live replies from you
limits.py       In-memory rate limiter
ingest.py       Builds the ChromaDB index from knowledge/
styles.py       UI theme and HTML
knowledge/      Your bio (summary.txt), resume and docs
tests/          Config, failure-path and hardening tests (python tests/test_config.py, ...)
Dockerfile, .dockerignore, .gcloudignore, firebase.json, .env.example
```

## Troubleshooting

| Problem | Fix |
| :--- | :--- |
| `ModuleNotFoundError` | Activate the venv: `source .venv/bin/activate`, then `pip install -r requirements.txt` |
| Answers don't use my documents | Run `python ingest.py` and check it reports chunks stored |
| Port 7860 in use | Set `PORT=7861` in `.env` |
| App stops with "Invalid agent config" | Fix the line it names in `agent.yaml`; it lists every problem found |
| App stops with "USER_NAME is not set" | Set `USER_NAME` in `.env` (or the environment) |
| Visitors wait on each other | Raise `MAX_CONCURRENT_CHATS` (default 10) |
| Telegram `409 Conflict` | Another instance uses the same bot token — stop it, or `curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"` |
| Calendar `404 Not Found` | Share your calendar with the service account email (see Google Calendar above) |

## Contributing

Issues and pull requests are welcome. Run `python3 -m py_compile *.py tests/*.py` and the four test files before submitting: `python3 tests/test_config.py`, `python3 tests/test_handoff.py`, `python3 tests/test_prod_fixes.py` and `python3 tests/test_guards.py`.

## License

MIT — see `LICENSE`.
