import sys
import re
import time
import random
import pickle
import unicodedata
from datetime import datetime

import google.auth.exceptions
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account

# =============================================================================
# RUNTIME CONTROL
# =============================================================================

START_TIME   = time.time()
MAX_RUNTIME  = 240 * 60  # 4 hours in seconds

# =============================================================================
# AUTHENTICATE — YOUTUBE
# =============================================================================

with open("youtube_token.pkl", "rb") as f:
    credentials = pickle.load(f)

if credentials.expired and credentials.refresh_token:
    print("Token expired — refreshing...")
    credentials.refresh(Request())
    with open("youtube_token.pkl", "wb") as f:
        pickle.dump(credentials, f)
    print("Token refreshed successfully.")
elif not credentials.valid:
    print("Token is invalid and cannot be refreshed. Please re-authenticate.")
    sys.exit(1)

youtube = build("youtube", "v3", credentials=credentials)

# =============================================================================
# AUTHENTICATE — GOOGLE SHEETS
# =============================================================================

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

sheet_credentials = service_account.Credentials.from_service_account_file(
    "credentials.json",
    scopes=SHEETS_SCOPES,
)

sheets_service  = build("sheets", "v4", credentials=sheet_credentials)
SPREADSHEET_ID  = "137DqmPMinL0hl2YGVNmi-wBl0uoz7keZu3ANUfOgG4A"

# Sheet names — main sheet uses current month; feature sheets are prefixed
SHEET_NAME           = datetime.now().strftime("%B %Y")        # e.g. "April 2026"
TESTIMONY_SHEET_NAME = f"Testimonies - {SHEET_NAME}"
OFFERING_SHEET_NAME  = f"Offerings - {SHEET_NAME}"

# =============================================================================
# SHEET SETUP
# =============================================================================

def ensure_sheet_exists(title: str) -> None:
    """Create a sheet tab with the given title if it does not already exist."""
    try:
        metadata     = sheets_service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheet_titles = [s["properties"]["title"] for s in metadata["sheets"]]

        if title not in sheet_titles:
            print(f"Creating new sheet: {title}")
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
            ).execute()

    except Exception as e:
        print(f"Sheet creation error for '{title}':", str(e))


ensure_sheet_exists(SHEET_NAME)
ensure_sheet_exists(TESTIMONY_SHEET_NAME)
ensure_sheet_exists(OFFERING_SHEET_NAME)

# =============================================================================
# CONNECT TO ACTIVE LIVE BROADCAST
# =============================================================================

try:
    broadcast_response = youtube.liveBroadcasts().list(
        part="snippet",
        broadcastStatus="active",
        broadcastType="all",
    ).execute()

    if not broadcast_response["items"]:
        print("No active live broadcast found.")
        sys.exit(1)

    live_chat_id = broadcast_response["items"][0]["snippet"]["liveChatId"]
    print("Connected to YouTube Live Chat!")

except HttpError as e:
    print("YouTube connection error:", e)
    sys.exit(1)

# =============================================================================
# BOT IDENTITY
# =============================================================================

BOT_NAMES = {"evangelistrambabu", "evangelistrambaburambo"}

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def remove_emojis(text: str) -> str:
    """Strip emoji / symbol characters from a string."""
    return "".join(c for c in text if not unicodedata.category(c).startswith("So"))


def send_message(text: str) -> None:
    """Post a message to the active YouTube live chat."""
    try:
        youtube.liveChatMessages().insert(
            part="snippet",
            body={
                "snippet": {
                    "liveChatId": live_chat_id,
                    "type": "textMessageEvent",
                    "textMessageDetails": {"messageText": remove_emojis(text)},
                }
            },
        ).execute()
        print("Reply sent.")

    except HttpError as e:
        print("YouTube send error:", e)


def extract_amount(text: str) -> str:
    """
    Extract a numeric amount from a message, e.g. 'I want to sow Rs. 500'.
    Returns the amount as a string, or 'Not specified' if none found.
    """
    match = re.search(
        r"(?:rs\.?|inr|rupees?)?\s*(\d[\d,]*(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    return match.group(1).replace(",", "") if match else "Not specified"

# =============================================================================
# GOOGLE SHEETS — WRITE FUNCTIONS
# =============================================================================

def _append_rows(sheet_name: str, values: list) -> None:
    """Generic helper to append rows to a named sheet."""
    try:
        col_end = chr(ord("A") + len(values[0]) - 1)  # e.g. 3 cols -> "C"
        result  = sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{sheet_name}!A:{col_end}",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()
        print(f"[{sheet_name}] Write success:", result)

    except Exception as e:
        print(f"[{sheet_name}] Write error:", str(e))


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def add_prayer_request(name: str, message: str) -> None:
    """Columns: Timestamp | Name | Message"""
    _append_rows(SHEET_NAME, [[_timestamp(), name.strip(), remove_emojis(message).strip()]])


def add_testimony(name: str, message: str) -> None:
    """Columns: Timestamp | Name | Testimony"""
    _append_rows(TESTIMONY_SHEET_NAME, [[_timestamp(), name.strip(), remove_emojis(message).strip()]])


def add_offering(name: str, message: str, amount: str) -> None:
    """Columns: Timestamp | Name | Message | Amount"""
    _append_rows(OFFERING_SHEET_NAME, [[_timestamp(), name.strip(), remove_emojis(message).strip(), amount]])

# =============================================================================
# DETECTION FUNCTIONS
# =============================================================================

def is_prayer_request(text: str) -> bool:
    keywords = [
        "pray for", "prayer request", "please pray",
        "prarthna", "prayer", "prathna", "dua",
        "praying", "need prayer", "pray",
    ]
    t = text.lower()
    return any(k in t for k in keywords)


def is_testimony(text: str) -> bool:
    """
    Detects healings, deliverances, and testimonies.
    Intentionally separate from prayer requests.
    """
    keywords = [
        "testimony", "healed", "healing", "been healed", "god healed",
        "delivered", "been delivered", "god delivered", "miracle",
        "i am healed", "i got healed", "jesus healed", "saved", "restored",
        "cancer gone", "pain gone", "sickness gone", "set free",
        "i testify", "i want to testify", "giving testimony",
        "my testimony", "share testimony",
    ]
    t = text.lower()
    return any(k in t for k in keywords)


def is_offering(text: str) -> bool:
    """Detects intent to give an offering, sow a seed, tithe, etc."""
    keywords = [
        "offering", "sow", "sowing", "seed", "tithe", "tithing",
        "give offering", "i want to give", "i want to sow",
        "i want to tithe", "i want to donate", "donate",
        "first fruit", "firstfruit", "first fruits",
        "i am sowing", "sowing a seed", "planting a seed",
        "kingdom giving", "i give", "i am giving",
        "ready to give", "ready to sow", "ready to offer",
    ]
    t = text.lower()
    return any(k in t for k in keywords)


def is_giving_question(text: str) -> bool:
    """Detects questions about HOW or WHERE to give/sow — replies with Razorpay link only."""
    patterns = [
        r"how (do i|can i|to) (give|sow|offer|tithe|donate|pay)",
        r"(where|how) (do i|can i|to) (give|sow|tithe|donate)",
        r"(giving|sowing|offering|payment) (link|details|info|method|process|procedure)",
        r"how (to|do i) (make|send) (an? )?(offering|donation|payment|tithe)",
        r"(payment|donate|giving) (link|details|page|portal)",
        r"how (do i|can i) support",
        r"where (do i|can i) (give|sow|donate|tithe)",
        r"(send|transfer) (money|funds|offering|tithe)",
    ]
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def is_address_request(text: str) -> bool:
    keywords = [
        "address", "location", "where is the church",
        "church address", "where are you located",
        "how to reach", "directions", "where is church",
    ]
    t = text.lower()
    return any(k in t for k in keywords)

# =============================================================================
# REPLY CONSTANTS & TEMPLATES
# =============================================================================

RAZORPAY_LINK  = "https://pages.razorpay.com/rwogiving"
CHURCH_ADDRESS = (
    "Holy Spirit Generation Church Nc Arena, "
    "Near Legacy School & Moto Mind Shop Byrithi, "
    "Kothanur, Bangalore - 560077, Karnataka"
)

PRAYER_REPLIES = [
    "@{name} Thank you for sending your prayer request. We are praying for you.",
    "@{name} Thank you for sharing your prayer need. Stay encouraged!",
    "@{name} We've received your prayer request. The Lord hears and answers prayer.",
]

TESTIMONY_REPLIES = [
    "@{name} Praise God! Thank you for sharing your testimony. To God be the glory!",
    "@{name} Hallelujah! We rejoice with you. Thank you for testifying of God's goodness!",
    "@{name} Amen! Thank you for sharing. God's power is still at work!",
]

OFFERING_REPLIES = [
    f"@{{name}} God bless you for your heart to give! To sow online: {RAZORPAY_LINK}",
    f"@{{name}} Amen! Thank you for your generosity. You can give here: {RAZORPAY_LINK}",
    f"@{{name}} The Lord loves a cheerful giver! Give online here: {RAZORPAY_LINK}",
]

GIVING_QUESTION_REPLY = (
    f"@{{name}} To give your offering or sow a seed online, use this link: "
    f"{RAZORPAY_LINK} — God bless you!"
)

ADDRESS_REPLY = f"@{{name}} Our church address: {CHURCH_ADDRESS}"

# =============================================================================
# MAIN LOOP — LISTEN TO LIVE CHAT
# =============================================================================

print("Listening for live chat messages...")

next_page_token       = None
processed_message_ids = set()

while time.time() - START_TIME < MAX_RUNTIME:
    try:
        chat_response = youtube.liveChatMessages().list(
            liveChatId=live_chat_id,
            part="snippet,authorDetails",
            pageToken=next_page_token,
        ).execute()

        for message in chat_response.get("items", []):
            msg_id = message["id"]

            if msg_id in processed_message_ids:
                continue
            processed_message_ids.add(msg_id)

            # Keep memory bounded — retain last 2000 IDs when cap is hit
            if len(processed_message_ids) > 5000:
                processed_message_ids = set(list(processed_message_ids)[-2000:])

            if "displayMessage" not in message["snippet"]:
                continue

            author = remove_emojis(message["authorDetails"]["displayName"])
            text   = remove_emojis(message["snippet"]["displayMessage"])

            # Skip messages from the bot itself
            if any(b in author.lower().replace(" ", "") for b in BOT_NAMES):
                continue

            # ------------------------------------------------------------------
            # Detection priority order:
            #   1. Prayer request  -> log to main sheet, send reply
            #   2. Testimony       -> log to Testimonies sheet, send reply
            #   3. Giving question -> send Razorpay link only (no sheet entry)
            #   4. Offering intent -> log to Offerings sheet, send reply + link
            #   5. Address request -> send church address
            # ------------------------------------------------------------------

            if is_prayer_request(text):
                print(f"[PRAYER]       {author}: {text}")
                add_prayer_request(author, text)
                send_message(random.choice(PRAYER_REPLIES).format(name=author))

            elif is_testimony(text):
                print(f"[TESTIMONY]    {author}: {text}")
                add_testimony(author, text)
                send_message(random.choice(TESTIMONY_REPLIES).format(name=author))

            elif is_giving_question(text):
                print(f"[HOW-TO-GIVE]  {author}: {text}")
                send_message(GIVING_QUESTION_REPLY.format(name=author))

            elif is_offering(text):
                print(f"[OFFERING]     {author}: {text}")
                amount = extract_amount(text)
                add_offering(author, text, amount)
                send_message(random.choice(OFFERING_REPLIES).format(name=author))

            elif is_address_request(text):
                print(f"[ADDRESS]      {author}: {text}")
                send_message(ADDRESS_REPLY.format(name=author))

        next_page_token = chat_response.get("nextPageToken")
        time.sleep(int(chat_response["pollingIntervalMillis"]) / 1000)

    except HttpError as e:
        print("YouTube API error:", e)
        time.sleep(5)

    except google.auth.exceptions.TransportError as e:
        print("Auth/transport error:", e)
        time.sleep(10)

    except google.auth.exceptions.RefreshError as e:
        print("Token refresh failed during run:", e)
        sys.exit(1)

    except Exception as e:
        print("Unexpected error:", e)
        time.sleep(5)

print("Bot execution completed.")
