from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from datetime import datetime
import time
import unicodedata
import random
import pickle

# -------------------------
# Runtime Control (IMPORTANT)
# -------------------------
START_TIME = time.time()
MAX_RUNTIME = 240* 60  # 4hrs

# -------------------------
# Step 1: Authenticate YouTube (Token-based, Headless Safe)
# -------------------------
with open("youtube_token.pkl", "rb") as f:
    credentials = pickle.load(f)

youtube = build("youtube", "v3", credentials=credentials)

# -------------------------
# Step 2: Authenticate Google Sheets (Service Account)
# -------------------------
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

sheet_credentials = service_account.Credentials.from_service_account_file(
    "credentials.json", scopes=SHEETS_SCOPES
)

sheets_service = build("sheets", "v4", credentials=sheet_credentials)

SPREADSHEET_ID = "137DqmPMinL0hl2YGVNmi-wBl0uoz7keZu3ANUfOgG4A"
SHEET_NAME = "PrayerRequests"

# -------------------------
# Step 3: Get Active Live Chat ID
# -------------------------
try:
    response = youtube.liveBroadcasts().list(
        part="snippet",
        broadcastStatus="active",
        broadcastType="all"
    ).execute()

    if not response["items"]:
        print("No active live broadcast found.")
        exit()

    live_chat_id = response["items"][0]["snippet"]["liveChatId"]
    print("Connected to YouTube Live Chat!")

except HttpError as e:
    print("Error connecting to YouTube:", e)
    exit()

# -------------------------
# Helper Functions
# -------------------------
def remove_emojis(text):
    return ''.join(c for c in text if not unicodedata.category(c).startswith('So'))

def send_message(text):
    clean_text = remove_emojis(text)
    try:
        youtube.liveChatMessages().insert(
            part="snippet",
            body={
                "snippet": {
                    "liveChatId": live_chat_id,
                    "type": "textMessageEvent",
                    "textMessageDetails": {
                        "messageText": clean_text
                    }
                }
            }
        ).execute()
        print(f"Sent reply to chat")
    except HttpError as e:
        print("Error sending message:", e)

def add_to_sheet(name, request_text):
    values = [[
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        name.strip(),
        remove_emojis(request_text).strip()
    ]]
    try:
        sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A:C",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values}
        ).execute()
        print(f"Saved prayer request from {name}")
    except HttpError as e:
        print("Sheets error:", e)

def is_prayer_request(text):
    keywords = [
        "pray for", "prayer request", "please pray",
        "prarthna", "prayer", "prathna", "dua",
        "praying", "need prayer"
    ]
    text = text.lower()
    return any(k in text for k in keywords)

# -------------------------
# Response Templates
# -------------------------
RESPONSE_TEMPLATES = [
    "@{name} Thank you for sending in your prayer request. We are praying for you. By His stripes, healing is already provided.",
    "@{name} Thank you for sharing your prayer need. Stay encouraged!",
    "@{name} We’ve received your prayer request. The Lord hears and answers prayer."
]

# -------------------------
# Listen to Chat
# -------------------------
print("Listening for live chat messages...")
next_page_token = None
processed_message_ids = set()
BOT_NAMES = ["evangelistrambabu", "evangelistrambaburambo"]

while time.time() - START_TIME < MAX_RUNTIME:
    try:
        response = youtube.liveChatMessages().list(
            liveChatId=live_chat_id,
            part="snippet,authorDetails",
            pageToken=next_page_token
        ).execute()

        for message in response.get("items", []):
            msg_id = message["id"]
            if msg_id in processed_message_ids:
                continue
            processed_message_ids.add(msg_id)

            if "displayMessage" not in message["snippet"]:
                continue

            author = remove_emojis(message["authorDetails"]["displayName"])
            text = remove_emojis(message["snippet"]["displayMessage"])

            if any(b in author.lower().replace(" ", "") for b in BOT_NAMES):
                continue

            if is_prayer_request(text):
                add_to_sheet(author, text)
                reply = random.choice(RESPONSE_TEMPLATES).format(name=author)
                send_message(reply)

        next_page_token = response.get("nextPageToken")
        time.sleep(int(response["pollingIntervalMillis"]) / 1000)

    except HttpError as e:
        print("YouTube API error:", e)
        time.sleep(5)

print("Bot execution completed.")
