# ONIRIA WhatsApp Chatbot

Simple architecture:

WhatsApp -> Twilio -> Flask on Render -> Gemini -> Twilio -> WhatsApp

## 1. GitHub

Upload these files to your GitHub repository:

- app.py
- requirements.txt
- .env.example
- .gitignore

Do NOT upload your real API keys or Google service-account JSON.

## 2. Render

Create a new Web Service from the GitHub repository.

Build command:

pip install -r requirements.txt

Start command:

gunicorn app:app

## 3. Render Environment Variables

Add:

GEMINI_API_KEY
GEMINI_MODEL
BRAIN_FOLDER_ID
GOOGLE_SERVICE_ACCOUNT_JSON
BRAIN_CACHE_TTL

Use the complete Google service-account JSON as the value of
GOOGLE_SERVICE_ACCOUNT_JSON.

## 4. Google Drive Brain

Share your Google Drive Brain folder with the service-account email.

The chatbot reads Google Docs, .md files, and .txt files.

## 5. Twilio

After Render deploys, copy your Render URL.

Example:

https://your-app.onrender.com

In Twilio WhatsApp configuration, set the incoming message webhook to:

https://your-app.onrender.com/whatsapp

Use HTTP POST.

## 6. Test

Open:

https://your-app.onrender.com/

You should see:

ONIRIA WhatsApp chatbot is running.

To test the Drive Brain:

https://your-app.onrender.com/debug-brain

The chatbot keeps only a short conversation history in memory.
If Render restarts, that temporary history is cleared.

There is intentionally no Baileys, QR code, Slack integration, database,
or local WhatsApp session in this version.
