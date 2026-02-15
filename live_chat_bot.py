from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from datetime import datetime
import time
import unicodedata
import random
import pickle

# -------------------------
# Runtime Control
# -------------------------
START_TIME = time.time()
MAX_RUNTIME = 240 * 60  # 4 hours

# -------------------------
# Authenticate YouTube
# -------------------------
with open("youtube_token.pkl", "rb") as f:
    credentials = pickle.load(f)

youtube = build("youtube", "v3", credentials=credentials)

# -------------------------
# Authenticate Google Sheets
# -------------------------
SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

sheet_credentials = service_account.Credentials.from_service_account_file(
    "credentials.json",
    scopes=SHEETS_SCOPES
)

sheets_service = build("sheets", "v4", credentials=sheet_credentials)

SPREADSHEET_ID = "137DqmPMinL0hl2YGVNmi-wBl0uoz7keZu3ANUfOgG4A"

# Automatically use current month as sheet name
SHEET_NAME = datetime.now().strftime("%B %Y")

# -------------------------
# Ensure Monthly Sheet Exists
# -------------------------
def ensure_sheet_exists():
    try:
        metadata = sheets_service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID
        ).execute()

        sheet_titles = [s["properties"]["title"] for s in metadata["sheets"]]

        if SHEET_NAME not in sheet_titles:
            print(f"Creating new sheet: {SHEET_NAME}")

            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={
                    "requests": [{
                        "addSheet": {
                            "properties": {
                                "title": SHEET_NAME
                            }
                        }
                    }]
                }
            ).execute()

    except Exception as e:
        print("Sheet creation error:", str(e))

ensure_sheet_exists()

# -------------------------
# Get Active Live Chat ID
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
    print("YouTube connection error:", e)
    exit()

# -------------------------
# Helper Functions
# -------------------------
def remove_emojis(text):
    return ''.join(c for c in text if not unicodedata.category(c).startswith('So'))

def send_message(text):
    try:
        youtube.liveChatMessages().insert(
            part="snippet",
            body={
                "snippet": {
                    "liveChatId": live_chat_id,
                    "type": "textMessageEvent",
                    "textMessageDetails": {
                        "messageText": remove_emojis(text)
                    }
                }
            }
        ).execute()
        print("Reply sent")

    except HttpError as e:
        print("YouTube send error:", e)

def add_to_sheet(name, request_text):
    values = [[
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        name.strip(),
        remove_emojis(request_text).strip()
    ]]

    try:
        result = sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A:C",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values}
        ).execute()

        print("Sheet write success:", result)

    except Exception as e:
        print("Sheets error:", str(e))

def is_prayer_request(text):
    keywords = [
        "pray for", "prayer request", "please pray",
        "prarthna", "prayer", "prathna", "dua",
        "praying", "need prayer"
    ]
    return any(k in text.lower() for k in keywords)

# -------------------------
# Response Templates
# -------------------------
RESPONSE_TEMPLATES = [
    "@{name} Thank you for sending your prayer request. We are praying for you.",
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
                print(f"Prayer request detected from {author}")
                add_to_sheet(author, text)

                reply = random.choice(RESPONSE_TEMPLATES).format(name=author)
                send_message(reply)

        next_page_token = response.get("nextPageToken")
        time.sleep(int(response["pollingIntervalMillis"]) / 1000)

    except HttpError as e:
        print("YouTube API error:", e)
        time.sleep(5)

print("Bot execution completed.")
