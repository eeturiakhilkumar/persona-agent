# 🤖 persona-agent

An open-source AI agent that talks to people **on your behalf**. Put it on your portfolio or personal site and it will answer questions about you, qualify recruiters and clients, book meetings, and ping you when it needs your input.

Everything about *you* (name, bio, skills, documents) comes from config files, so anyone can fork this, fill in their details, and deploy their own agent in about 10 minutes.

## What it does

| Capability | How |
| :--- | :--- |
| Answers questions about you from your resume and docs | RAG over `knowledge/` using ChromaDB + OpenAI embeddings |
| Screens recruiters (company, stack, comp, remote/hybrid) | Logs a lead and notifies you |
| Scopes client projects (problem, budget, timeline) | Logs a lead and notifies you |
| Books meetings with a Google Meet link | Google Calendar (optional) |
| Asks **you** when it doesn't know the answer | Telegram, waits ~60s for your reply (optional) |
| Phone alerts for every new lead | Pushover (optional) |
| Stores leads and chat transcripts | Firestore (optional; otherwise printed to the console) |

Only an **OpenAI API key** is required. Every other integration turns on automatically when you add its credentials.

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

**1. Tell it who you are** — edit `.env`:

```env
USER_NAME="Your Full Name"
USER_TITLE="Your Professional Title"
USER_LOCATION="City, Country"
USER_EMAIL="you@example.com"
USER_SKILLS="Python, React, Cloud Architecture"
USER_CALENDAR_URL=""      # optional booking link, e.g. https://cal.com/you
USER_LINKEDIN_URL=""      # optional
USER_GITHUB_URL=""        # optional
OPENAI_API_KEY="sk-..."
```

**2. Write your bio** — replace the sample text in `knowledge/summary.txt` with 2–4 paragraphs about your background, specialties and the work you want. It is shown in the sidebar and given to the agent.

**3. Add your documents** — drop your resume (PDF), project write-ups (`.md`) or notes (`.txt`) into `knowledge/`. These files are git-ignored (only the sample `summary.txt` is tracked), so your resume never lands in a public repo by accident. The agent builds its search index automatically the first time it starts. After changing files in `knowledge/`, rebuild it:

```bash
python ingest.py
```

**4. Run it**

```bash
python app.py
```

Open <http://localhost:7860>. Done. 🎉

> The sample profile ("Alex Morgan") is shown until you set your own values in `.env` and `knowledge/summary.txt`.

---

## Optional integrations

Add these to `.env` only if you want them.

<details>
<summary><b>Telegram — let the agent ask you questions live</b></summary>

1. In Telegram, message `@BotFather`, run `/newbot`, and copy the token to `TELEGRAM_BOT_TOKEN`.
2. Message `@userinfobot` to get your numeric ID and put it in `TELEGRAM_CHAT_ID`.
3. Send any message to your new bot once so it can reach you.

When a visitor asks something the agent can't answer, it messages you. **Swipe-reply** to that message and your answer appears in the web chat. Run only one instance per bot token.
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
  --set-env-vars "USER_NAME=Your Full Name,USER_TITLE=Your Title,USER_EMAIL=you@example.com,OPENAI_API_KEY=sk-..."
```

Cloud Run prints your public URL — that's your live agent. Your `knowledge/` files are baked into the image and the search index is built when the container first starts.

> **Keep secrets out of the image.** `.env` and key files are excluded by `.dockerignore`. Pass credentials as env vars (above), or better, store them in [Secret Manager](https://cloud.google.com/run/docs/configuring/services/secrets).

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

## ⚠️ Before you go public

- **Cost:** anyone who finds the URL can chat, and every message uses your OpenAI credits. Set a monthly spend limit in your OpenAI dashboard and, on Cloud Run, a low `--max-instances` (e.g. `3`).
- **Privacy:** visitors' names, emails and chat transcripts are stored in your Firestore if you enable it. Tell visitors, and follow the privacy rules that apply to you.
- **Never commit** `.env`, `serviceAccountKey.json` or `calendar_service_account.json` (already in `.gitignore`).

---

## Project layout

```
app.py          Gradio app, chat loop, Telegram escalation
config.py       Loads .env, profile values and shared constants
context.py      System prompt built from your profile
tools.py        Agent tools: leads, knowledge search, calendar, escalation
ingest.py       Builds the ChromaDB index from knowledge/
styles.py       UI theme and HTML
knowledge/      Your bio (summary.txt), resume and docs
Dockerfile, firebase.json, .env.example
```

## Troubleshooting

| Problem | Fix |
| :--- | :--- |
| `ModuleNotFoundError` | Activate the venv: `source .venv/bin/activate`, then `pip install -r requirements.txt` |
| Answers don't use my documents | Run `python ingest.py` and check it reports chunks stored |
| Port 7860 in use | Set `PORT=7861` in `.env` |
| Telegram `409 Conflict` | Another instance uses the same bot token — stop it, or `curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"` |
| Calendar `404 Not Found` | Share your calendar with the service account email (see Google Calendar above) |

## Contributing

Issues and pull requests are welcome. Run `python3 -m py_compile *.py` before submitting.

## License

MIT — see `LICENSE`.
