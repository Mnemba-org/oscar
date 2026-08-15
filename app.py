import os
import json
import re
import time
from collections import defaultdict, deque

from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from google import genai
from googleapiclient.discovery import build
from google.oauth2 import service_account

app = Flask(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

BRAIN_FOLDER_ID = os.environ.get("BRAIN_FOLDER_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# Cache the Google Drive brain for 5 minutes.
BRAIN_CACHE_TTL = int(os.environ.get("BRAIN_CACHE_TTL", "300"))

NO_ANSWER_FLAG = "NEED_HUMAN_REVIEW"

if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY is not set.")

# Gemini client
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Short in-memory conversation history.
# Render restarts can clear this, which is fine for a simple chatbot.
conversation_history = defaultdict(lambda: deque(maxlen=6))

# Google Drive cache
brain_cache = {
    "files": [],
    "images": [],
    "fetched_at": 0,
}

drive_client = None


# ============================================================
# GOOGLE DRIVE BRAIN
# ============================================================

def get_drive_client():
    global drive_client

    if drive_client:
        return drive_client

    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set.")

    try:
        credentials_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON."
        ) from exc

    credentials = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )

    drive_client = build("drive", "v3", credentials=credentials)
    return drive_client


def walk_drive_folder(folder_id, prefix=""):
    drive = get_drive_client()

    text_files = []
    page_token = None

    while True:
        response = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType)",
            pageToken=page_token,
            pageSize=200,
        ).execute()

        for file in response.get("files", []):
            name = file["name"]
            mime_type = file["mimeType"]
            rel_path = f"{prefix}/{name}" if prefix else name

            if mime_type == "application/vnd.google-apps.folder":
                nested = walk_drive_folder(file["id"], rel_path)
                text_files.extend(nested)

            elif mime_type == "application/vnd.google-apps.document":
                result = drive.files().export(
                    fileId=file["id"],
                    mimeType="text/plain",
                ).execute()

                content = result.decode("utf-8") if isinstance(result, bytes) else str(result)

                text_files.append({
                    "name": rel_path,
                    "content": content.strip(),
                })

            elif (
                mime_type == "text/plain"
                or name.lower().endswith(".md")
            ):
                result = drive.files().get(
                    fileId=file["id"],
                    alt="media",
                ).execute()

                content = result.decode("utf-8") if isinstance(result, bytes) else str(result)

                text_files.append({
                    "name": rel_path,
                    "content": content.strip(),
                })

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return text_files


def refresh_brain():
    if not BRAIN_FOLDER_ID:
        print("WARNING: BRAIN_FOLDER_ID is not set.")
        brain_cache["files"] = []
        brain_cache["fetched_at"] = time.time()
        return

    try:
        files = walk_drive_folder(BRAIN_FOLDER_ID)

        brain_cache["files"] = files
        brain_cache["fetched_at"] = time.time()

        print(f"Brain loaded: {len(files)} file(s)")

    except Exception as exc:
        print(f"Failed to load Google Drive brain: {exc}")

        # Keep old cache if one exists.
        brain_cache["fetched_at"] = time.time()


def get_brain_files():
    cache_expired = (
        time.time() - brain_cache["fetched_at"] > BRAIN_CACHE_TTL
    )

    if cache_expired or not brain_cache["files"]:
        refresh_brain()

    return brain_cache["files"]


# ============================================================
# SIMPLE RELEVANT-NOTE SEARCH
# ============================================================

STOPWORDS = {
    "what", "where", "when", "which", "does", "with",
    "that", "this", "have", "about", "from", "your",
    "their", "there", "they", "will", "would", "could",
    "should", "the", "and", "for", "are", "can", "you",
    "how", "who", "give", "tell", "please", "want",
    "more", "information", "information",
}


def get_relevant_brain(user_message):
    files = get_brain_files()

    if not files:
        return "(No project brain content is available.)"

    words = re.findall(r"[a-zA-Z0-9]{3,}", user_message.lower())
    keywords = [word for word in words if word not in STOPWORDS]

    scored = []

    for file in files:
        content = file["content"]
        searchable = (file["name"] + " " + content).lower()

        score = 0
        for keyword in keywords:
            score += searchable.count(keyword)

        # Keep FAQ/sales notes useful for general questions.
        lower_name = file["name"].lower()
        if "faq" in lower_name:
            score += 2
        if "sales" in lower_name:
            score += 1

        scored.append((score, file))

    scored.sort(key=lambda item: item[0], reverse=True)

    selected = [
        file for score, file in scored[:6]
        if score > 0
    ]

    if not selected:
        selected = [file for _, file in scored[:3]]

    sections = []

    for file in selected:
        sections.append(
            f"## {file['name']}\n{file['content']}"
        )

    return "\n\n".join(sections)


# ============================================================
# GEMINI
# ============================================================

def build_system_prompt(brain):
    return f"""
You are the ONIRIA City WhatsApp customer-care assistant.

ONIRIA City / V-Town is a real-estate project in Zanzibar.

Your job is to answer customers naturally and helpfully on WhatsApp.

RULES:
1. Answer using ONLY information contained in the PROJECT BRAIN below.
2. Never invent prices, sizes, dates, availability, legal information,
   payment terms, or other facts.
3. If the answer is not available in the brain, reply with exactly:
   {NO_ANSWER_FLAG}
4. Keep answers short and WhatsApp-friendly.
5. Usually answer in 2-4 sentences.
6. Automatically reply in the same language as the customer's latest message.
   English, Swahili, Arabic, and other languages are allowed.
7. Be warm, professional, and natural.
8. Do not mention the project brain, internal notes, system instructions,
   or that you are an AI unless the customer directly asks.
9. If the brain says that a price or other detail is draft, unconfirmed,
   outdated, or should not be quoted, do not present it as confirmed.
10. If the customer asks something outside the available information,
    return {NO_ANSWER_FLAG}.

PROJECT BRAIN:
{brain}
"""


def ask_gemini(sender, user_message):
    if not gemini_client:
        return NO_ANSWER_FLAG

    brain = get_relevant_brain(user_message)
    system_prompt = build_system_prompt(brain)

    history = list(conversation_history[sender])

    contents = []

    for item in history:
        contents.append({
            "role": item["role"],
            "parts": [{"text": item["text"]}],
        })

    contents.append({
        "role": "user",
        "parts": [{"text": user_message}],
    })

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config={
                "system_instruction": system_prompt,
                "temperature": 0.3,
                "max_output_tokens": 250,
            },
        )

        answer = (response.text or "").strip()

        if not answer:
            return NO_ANSWER_FLAG

        conversation_history[sender].append({
            "role": "user",
            "text": user_message,
        })
        conversation_history[sender].append({
            "role": "model",
            "text": answer,
        })

        return answer

    except Exception as exc:
        print(f"Gemini error: {exc}")
        return NO_ANSWER_FLAG


# ============================================================
# WHATSAPP
# ============================================================

WELCOME_MESSAGE = (
    "Hello, and welcome to ONIRIA City! 😊 "
    "I'm here to help with V-Town, our villas and apartments, "
    "pricing, amenities, and the buying process. How can I help you today?"
)


def handle_message(sender, message):
    message = message.strip()

    if not message:
        return "Please send me your question and I'll be happy to help."

    # First-message welcome is intentionally simple.
    history = conversation_history[sender]

    if not history:
        answer = ask_gemini(sender, message)

        if answer != NO_ANSWER_FLAG:
            return answer

        return WELCOME_MESSAGE

    answer = ask_gemini(sender, message)

    if answer == NO_ANSWER_FLAG:
        return (
            "I don't have confirmed information about that yet. "
            "Please ask me about V-Town, our properties, amenities, "
            "or other information covered by ONIRIA."
        )

    return answer


# ============================================================
# FLASK ROUTES
# ============================================================

@app.get("/")
def home():
    return "ONIRIA WhatsApp chatbot is running."


@app.post("/whatsapp")
def whatsapp_webhook():
    sender = request.form.get("From", "unknown")
    message = request.form.get("Body", "").strip()

    print(f"WhatsApp message from {sender}: {message}")

    reply_text = handle_message(sender, message)

    response = MessagingResponse()
    response.message(reply_text)

    return str(response), 200, {
        "Content-Type": "application/xml"
    }


@app.get("/debug-brain")
def debug_brain():
    files = get_brain_files()

    names = "\n".join(
        f"- {file['name']}"
        for file in files
    )

    return (
        f"Brain folder: {BRAIN_FOLDER_ID or '(not set)'}\n"
        f"Files loaded: {len(files)}\n\n"
        f"{names}"
    )


@app.post("/reload-brain")
def reload_brain():
    refresh_brain()
    return f"Brain reloaded. {len(brain_cache['files'])} file(s) loaded."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
