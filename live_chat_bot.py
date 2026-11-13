
import sys
import re
import time
import random
import pickle
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

import google.auth.exceptions
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account


# =============================================================================
# 1. RUNTIME CONTROL
# =============================================================================

START_TIME = time.time()
MAX_RUNTIME = 240 * 60  # 4 hours

IST = ZoneInfo("Asia/Kolkata")

REPLY_COOLDOWN_SECONDS = 60
SEND_INTERVAL_SECONDS = 2

last_replies = {}
last_send_time = 0


# =============================================================================
# 2. AUTHENTICATE — YOUTUBE
# =============================================================================

with open("youtube_token.pkl", "rb") as f:
    youtube_credentials = pickle.load(f)

if youtube_credentials.expired and youtube_credentials.refresh_token:
    print("Token expired — refreshing...")

    youtube_credentials.refresh(Request())

    with open("youtube_token.pkl", "wb") as f:
        pickle.dump(youtube_credentials, f)

    print("Token refreshed successfully.")

elif not youtube_credentials.valid:
    print("YouTube token is invalid. Please re-authenticate.")
    sys.exit(1)

youtube = build(
    "youtube",
    "v3",
    credentials=youtube_credentials
)


# =============================================================================
# 3. AUTHENTICATE — GOOGLE SHEETS
# =============================================================================

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

sheet_credentials = service_account.Credentials.from_service_account_file(
    "credentials.json",
    scopes=SHEETS_SCOPES,
)

sheets_service = build(
    "sheets",
    "v4",
    credentials=sheet_credentials
)

SPREADSHEET_ID = "137DqmPMinL0hl2YGVNmi-wBl0uoz7keZu3ANUfOgG4A"

SHEET_NAME = datetime.now(IST).strftime("%B %Y")
TESTIMONY_SHEET_NAME = f"Testimonies - {SHEET_NAME}"
OFFERING_SHEET_NAME = f"Offerings - {SHEET_NAME}"


# =============================================================================
# 4. BOT IDENTITY
# =============================================================================

# Normalized usernames. Spaces and @ symbols are removed before comparison.
BOT_NAMES = {
    "apostlerambaburambo",
    "evangelistrambabu",
    "evangelistrambaburambo",
}

BOT_CHANNEL_IDS = set()


def normalize_author(name):
    """Normalize a YouTube display name for identity comparison."""
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def get_bot_channel_identity():
    """
    Retrieve the authenticated YouTube channel ID.
    This is more reliable than checking the display name.
    """

    global BOT_CHANNEL_IDS

    try:
        response = youtube.channels().list(
            part="id",
            mine=True
        ).execute()

        BOT_CHANNEL_IDS = {
            channel["id"]
            for channel in response.get("items", [])
        }

        if BOT_CHANNEL_IDS:
            print("Bot channel identity verified.")
            print("Authenticated channel IDs:", BOT_CHANNEL_IDS)
        else:
            print("WARNING: No authenticated channel ID returned.")

    except HttpError as e:
        print("WARNING: Could not retrieve bot channel ID:", e)
        print("Username-based identity checking will be used.")


get_bot_channel_identity()


# =============================================================================
# 5. SHEET SETUP
# =============================================================================

def ensure_sheet_exists(title):
    """Create a sheet tab if it does not already exist."""

    try:
        metadata = sheets_service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID
        ).execute()

        sheet_titles = [
            sheet["properties"]["title"]
            for sheet in metadata.get("sheets", [])
        ]

        if title not in sheet_titles:
            print(f"Creating new sheet: {title}")

            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": title
                                }
                            }
                        }
                    ]
                }
            ).execute()

    except Exception as e:
        print(f"Sheet creation error for '{title}': {e}")


ensure_sheet_exists(SHEET_NAME)
ensure_sheet_exists(TESTIMONY_SHEET_NAME)
ensure_sheet_exists(OFFERING_SHEET_NAME)


# =============================================================================
# 6. CONNECT TO ACTIVE YOUTUBE LIVE BROADCAST
# =============================================================================

try:
    broadcast_response = youtube.liveBroadcasts().list(
        part="snippet",
        broadcastStatus="active",
        broadcastType="all",
    ).execute()

    if not broadcast_response.get("items"):
        print("No active live broadcast found.")
        sys.exit(1)

    live_chat_id = (
        broadcast_response["items"][0]["snippet"]["liveChatId"]
    )

    print("Connected to YouTube Live Chat!")

except HttpError as e:
    print("YouTube connection error:", e)
    sys.exit(1)


# =============================================================================
# 7. UTILITY FUNCTIONS
# =============================================================================

def remove_emojis(text):
    """Remove emoji and symbol characters."""

    return "".join(
        char
        for char in text
        if not unicodedata.category(char).startswith("So")
    )


def format_mention(name):
    """
    Format a YouTube username with exactly one leading @.
    """

    clean_name = remove_emojis(name).strip().lstrip("@").strip()

    return f"@{clean_name}" if clean_name else ""


def is_bot_message(author_details):
    """
    Identify messages sent by the bot itself.

    First checks the authenticated channel ID.
    Then uses normalized display name as a backup.
    """

    channel_id = author_details.get("channelId")

    # Most reliable check: YouTube channel ID
    if channel_id and channel_id in BOT_CHANNEL_IDS:
        return True

    # Backup check: normalized username
    display_name = author_details.get("displayName", "")

    if normalize_author(display_name) in BOT_NAMES:
        return True

    return False


def send_message(text):
    """Send a message to YouTube Live Chat with rate limiting."""

    global last_send_time

    try:
        elapsed = time.monotonic() - last_send_time

        if elapsed < SEND_INTERVAL_SECONDS:
            time.sleep(SEND_INTERVAL_SECONDS - elapsed)

        youtube.liveChatMessages().insert(
            part="snippet",
            body={
                "snippet": {
                    "liveChatId": live_chat_id,
                    "type": "textMessageEvent",
                    "textMessageDetails": {
                        "messageText": remove_emojis(text)
                    },
                }
            },
        ).execute()

        last_send_time = time.monotonic()

        print("[SENT]", text)

    except HttpError as e:
        print("YouTube send error:", e)


def extract_amount(text):
    """Extract a numeric amount from a message."""

    match = re.search(
        r"(?:rs\.?|inr|rupees?)?\s*(\d[\d,]*(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )

    return (
        match.group(1).replace(",", "")
        if match
        else "Not specified"
    )


def timestamp():
    """Return the current Indian Standard Time."""

    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


# =============================================================================
# 8. GOOGLE SHEETS — WRITE FUNCTIONS
# =============================================================================

def append_rows(sheet_name, values):
    """Append data to a Google Sheets tab."""

    try:
        col_end = chr(ord("A") + len(values[0]) - 1)

        result = sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!A:{col_end}",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()

        print(f"[{sheet_name}] Write successful.")

    except Exception as e:
        print(f"[{sheet_name}] Write error:", e)


def add_prayer_request(name, message):
    """Columns: Timestamp | Name | Message"""

    append_rows(
        SHEET_NAME,
        [[timestamp(), name.strip(), remove_emojis(message).strip()]]
    )


def add_testimony(name, message):
    """Columns: Timestamp | Name | Testimony"""

    append_rows(
        TESTIMONY_SHEET_NAME,
        [[timestamp(), name.strip(), remove_emojis(message).strip()]]
    )


def add_offering(name, message, amount):
    """Columns: Timestamp | Name | Message | Amount"""

    append_rows(
        OFFERING_SHEET_NAME,
        [[timestamp(), name.strip(), remove_emojis(message).strip(), amount]]
    )


# =============================================================================
# 9. MESSAGE DETECTION FUNCTIONS
# =============================================================================

def is_prayer_request(text):

    keywords = [
        "pray for",
        "pry for me",
        "pry me",
        "prayer request",
        "please pray",
        "prarthna",
        "prayer",
        "prathna",
        "dua",
        "praying",
        "need prayer",
        "pray",
    ]

    t = text.casefold()

    return any(keyword in t for keyword in keywords)


def is_testimony(text):

    keywords = [
        "testimony",
        "healed",
        "healing",
        "been healed",
        "god healed",
        "delivered",
        "been delivered",
        "god delivered",
        "miracle",
        "i am healed",
        "i got healed",
        "jesus healed",
        "saved",
        "restored",
        "cancer gone",
        "pain gone",
        "sickness gone",
        "set free",
        "i testify",
        "i want to testify",
        "giving testimony",
        "my testimony",
        "share testimony",
    ]

    t = text.casefold()

    return any(keyword in t for keyword in keywords)


def is_offering(text):

    keywords = [
        "offering",
        "sow",
        "sowing",
        "seed",
        "tithe",
        "tithing",
        "give offering",
        "i want to give",
        "i want to sow",
        "i want to tithe",
        "i want to donate",
        "donate",
        "first fruit",
        "firstfruit",
        "first fruits",
        "i am sowing",
        "sowing a seed",
        "planting a seed",
        "kingdom giving",
        "i give",
        "i am giving",
        "ready to give",
        "ready to sow",
        "ready to offer",
    ]

    t = text.casefold()

    return any(keyword in t for keyword in keywords)


def is_giving_question(text):

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

    t = text.casefold()

    return any(re.search(pattern, t) for pattern in patterns)


def is_address_request(text):

    keywords = [
        "address",
        "location",
        "where is the church",
        "church address",
        "where are you located",
        "how to reach",
        "directions",
        "where is church",
    ]

    t = text.casefold()

    return any(keyword in t for keyword in keywords)


# =============================================================================
# 10. REPLY TEMPLATES
# =============================================================================

RAZORPAY_LINK = "https://pages.razorpay.com/rwogiving"

CHURCH_ADDRESS = (
    "Holy Spirit Generation Church Nc Arena, "
    "Near Legacy School & Moto Mind Shop Byrithi, "
    "Kothanur, Bangalore - 560077, Karnataka"
)


PRAYER_REPLIES = [
    "{mention} Thank you for sharing your prayer need. Stay encouraged!",
    "{mention} We've received your prayer request. The Lord hears and answers prayer.",
    "{mention} Thank you for sharing your prayer request. We are praying for you.",
]


TESTIMONY_REPLIES = [
    "{mention} Praise God! Thank you for sharing your testimony. To God be the glory!",
    "{mention} Hallelujah! We rejoice with you. Thank you for testifying of God's goodness!",
    "{mention} Amen! Thank you for sharing. God's power is still at work!",
]


OFFERING_REPLIES = [
    f"{{mention}} God bless you for your heart to give! To sow online: {RAZORPAY_LINK}",
    f"{{mention}} Amen! Thank you for your generosity. You can give here: {RAZORPAY_LINK}",
    f"{{mention}} The Lord loves a cheerful giver! Give online here: {RAZORPAY_LINK}",
]


GIVING_QUESTION_REPLY = (
    f"{{mention}} To give your offering or sow a seed online, "
    f"use this link: {RAZORPAY_LINK} — God bless you!"
)


ADDRESS_REPLY = (
    f"{{mention}} Our church address: {CHURCH_ADDRESS}"
)


# =============================================================================
# 11. COOLDOWN PROTECTION
# =============================================================================

def is_on_cooldown(author_key, category):
    """
    Prevent repeated replies to the same user
    for the same category within the cooldown period.
    """

    key = (author_key, category)

    now = time.monotonic()

    previous_reply = last_replies.get(key)

    if previous_reply is not None:
        elapsed = now - previous_reply

        if elapsed < REPLY_COOLDOWN_SECONDS:
            print(
                f"[COOLDOWN] Skipping {category} from {author_key}"
            )
            return True

    return False


def record_reply(author_key, category):
    """Record a successful reply for cooldown tracking."""

    last_replies[(author_key, category)] = time.monotonic()


# =============================================================================
# 12. MESSAGE PROCESSING
# =============================================================================

def process_message(message):

    msg_id = message.get("id")

    snippet = message.get("snippet", {})
    author_details = message.get("authorDetails", {})

    # Ignore messages without a valid ID
    if not msg_id:
        return

    # Ignore bot's own messages
    if is_bot_message(author_details):
        print("[SKIPPED] Own bot message:", msg_id)
        return

    # Ignore messages without display text
    if "displayMessage" not in snippet:
        return

    author = remove_emojis(
        author_details.get("displayName", "")
    ).strip()

    text = remove_emojis(
        snippet.get("displayMessage", "")
    ).strip()

    if not author or not text:
        return

    mention = format_mention(author)

    # Prefer channel ID as cooldown identity
    author_key = (
        author_details.get("channelId")
        or normalize_author(author)
    )

    print(f"[MESSAGE] {author}: {text}")

    # -------------------------------------------------------------------------
    # DETECTION PRIORITY:
    # 1. Prayer request
    # 2. Testimony
    # 3. Giving question
    # 4. Offering
    # 5. Address request
    # -------------------------------------------------------------------------

    if is_prayer_request(text):

        category = "prayer"

        if is_on_cooldown(author_key, category):
            return

        print("[PRAYER]", author, text)

        add_prayer_request(author, text)

        reply = random.choice(PRAYER_REPLIES).format(
            mention=mention
        )

        send_message(reply)
        record_reply(author_key, category)

    elif is_testimony(text):

        category = "testimony"

        if is_on_cooldown(author_key, category):
            return

        print("[TESTIMONY]", author, text)

        add_testimony(author, text)

        reply = random.choice(TESTIMONY_REPLIES).format(
            mention=mention
        )

        send_message(reply)
        record_reply(author_key, category)

    elif is_giving_question(text):

        category = "giving_question"

        if is_on_cooldown(author_key, category):
            return

        print("[HOW-TO-GIVE]", author, text)

        reply = GIVING_QUESTION_REPLY.format(
            mention=mention
        )

        send_message(reply)
        record_reply(author_key, category)

    elif is_offering(text):

        category = "offering"

        if is_on_cooldown(author_key, category):
            return

        print("[OFFERING]", author, text)

        amount = extract_amount(text)

        add_offering(author, text, amount)

        reply = random.choice(OFFERING_REPLIES).format(
            mention=mention
        )

        send_message(reply)
        record_reply(author_key, category)

    elif is_address_request(text):

        category = "address"

        if is_on_cooldown(author_key, category):
            return

        print("[ADDRESS]", author, text)

        reply = ADDRESS_REPLY.format(
            mention=mention
        )

        send_message(reply)
        record_reply(author_key, category)


# =============================================================================
# 13. MAIN LOOP — LISTEN TO YOUTUBE LIVE CHAT
# =============================================================================

print("=" * 60)
print("YOUTUBE LIVE CHAT BOT STARTED")
print("=" * 60)

next_page_token = None

# Dictionary preserves insertion order, unlike an unordered set.
processed_message_ids = {}


while time.time() - START_TIME < MAX_RUNTIME:

    try:

        chat_response = youtube.liveChatMessages().list(
            liveChatId=live_chat_id,
            part="snippet,authorDetails",
            pageToken=next_page_token,
        ).execute()

        messages = chat_response.get("items", [])

        for message in messages:

            msg_id = message.get("id")

            # Prevent duplicate processing
            if not msg_id:
                continue

            if msg_id in processed_message_ids:
                continue

            processed_message_ids[msg_id] = True

            # Keep memory bounded
            if len(processed_message_ids) > 5000:
                oldest_id = next(iter(processed_message_ids))
                del processed_message_ids[oldest_id]

            # Process the message
            process_message(message)

        next_page_token = chat_response.get("nextPageToken")

        polling_interval = (
            chat_response.get("pollingIntervalMillis", 5000) / 1000
        )

        time.sleep(polling_interval)

    except HttpError as e:

        print("[YOUTUBE API ERROR]", e)

        time.sleep(5)

    except google.auth.exceptions.TransportError as e:

        print("[TRANSPORT ERROR]", e)

        time.sleep(10)

    except google.auth.exceptions.RefreshError as e:

        print("[TOKEN ERROR]", e)

        sys.exit(1)

    except Exception as e:

        print("[UNEXPECTED ERROR]", repr(e))

        time.sleep(5)


print("=" * 60)
print("BOT EXECUTION COMPLETED")
print("=" * 60)
