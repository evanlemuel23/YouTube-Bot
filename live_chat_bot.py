
import sys
import re
import time
import random
import pickle
import unicodedata
from collections import OrderedDict
from datetime import datetime
from zoneinfo import ZoneInfo

import google.auth.exceptions
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account


# =============================================================================
# 1. CONFIGURATION
# =============================================================================

START_TIME = time.time()
MAX_RUNTIME = 240 * 60

IST = ZoneInfo("Asia/Kolkata")

REPLY_COOLDOWN_SECONDS = 60
SEND_INTERVAL_SECONDS = 2
MAX_TRACKED_IDS = 5000

YOUTUBE_TOKEN_FILE = "youtube_token.pkl"
GOOGLE_CREDENTIALS_FILE = "credentials.json"

SPREADSHEET_ID = "137DqmPMinL0hl2YGVNmi-wBl0uoz7keZu3ANUfOgG4A"

BOT_NAMES = {
    "apostlerambaburambo",
    "evangelistrambabu",
    "evangelistrambaburambo",
}

BOT_CHANNEL_IDS = set()
SELF_SENT_MESSAGE_IDS = OrderedDict()

last_replies = {}
last_send_time = 0


# =============================================================================
# 2. AUTHENTICATE — YOUTUBE
# =============================================================================

try:
    with open(YOUTUBE_TOKEN_FILE, "rb") as f:
        youtube_credentials = pickle.load(f)
except FileNotFoundError:
    print(f"ERROR: {YOUTUBE_TOKEN_FILE} was not found.")
    sys.exit(1)

if youtube_credentials.expired and youtube_credentials.refresh_token:
    print("YouTube token expired — refreshing...")
    try:
        youtube_credentials.refresh(Request())
        with open(YOUTUBE_TOKEN_FILE, "wb") as f:
            pickle.dump(youtube_credentials, f)
        print("YouTube token refreshed successfully.")
    except Exception as e:
        print("ERROR: Could not refresh YouTube token:", repr(e))
        sys.exit(1)

elif not youtube_credentials.valid:
    print("ERROR: YouTube token is invalid. Re-authenticate.")
    sys.exit(1)

youtube = build(
    "youtube",
    "v3",
    credentials=youtube_credentials,
    cache_discovery=False,
)


# =============================================================================
# 3. AUTHENTICATE — GOOGLE SHEETS
# =============================================================================

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

try:
    sheet_credentials = service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE,
        scopes=SHEETS_SCOPES,
    )
except FileNotFoundError:
    print(f"ERROR: {GOOGLE_CREDENTIALS_FILE} was not found.")
    sys.exit(1)

sheets_service = build(
    "sheets",
    "v4",
    credentials=sheet_credentials,
    cache_discovery=False,
)

SHEET_NAME = datetime.now(IST).strftime("%B %Y")
TESTIMONY_SHEET_NAME = f"Testimonies - {SHEET_NAME}"
OFFERING_SHEET_NAME = f"Offerings - {SHEET_NAME}"


# =============================================================================
# 4. BOT IDENTITY AND MESSAGE FILTERS
# =============================================================================

def normalize_author(name):
    return re.sub(r"[^a-z0-9]", "", str(name).casefold())


def get_bot_channel_identity():
    global BOT_CHANNEL_IDS

    try:
        response = youtube.channels().list(
            part="id,snippet",
            mine=True,
        ).execute()

        BOT_CHANNEL_IDS = {
            item.get("id")
            for item in response.get("items", [])
            if item.get("id")
        }

        if BOT_CHANNEL_IDS:
            print(
                "[IDENTITY] Authenticated YouTube channel ID(s):",
                ", ".join(sorted(BOT_CHANNEL_IDS))
            )
        else:
            print("[WARNING] No authenticated channel ID returned.")

    except HttpError as e:
        print("[WARNING] Could not retrieve channel ID:", e)


def is_bot_message(author_details):

    if author_details.get("isChatOwner") is True:
        return True

    channel_id = author_details.get("channelId", "")

    if channel_id and channel_id in BOT_CHANNEL_IDS:
        return True

    display_name = author_details.get("displayName", "")

    if normalize_author(display_name) in BOT_NAMES:
        return True

    return False


def remember_self_message(message_id):

    if not message_id:
        return

    SELF_SENT_MESSAGE_IDS[message_id] = True
    SELF_SENT_MESSAGE_IDS.move_to_end(message_id)

    while len(SELF_SENT_MESSAGE_IDS) > MAX_TRACKED_IDS:
        SELF_SENT_MESSAGE_IDS.popitem(last=False)


def normalize_message(text):

    text = unicodedata.normalize("NFKC", str(text)).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:@\S+\s*)+", "", text)

    return text


BOT_REPLY_SIGNATURES = (
    "thank you for sharing your prayer need. stay encouraged!",
    "we've received your prayer request. the lord hears and answers prayer.",
    "thank you for sharing your prayer request. we are praying for you.",
    "thank you for sending your prayer request. we are praying for you.",
    "praise god! thank you for sharing your testimony.",
    "hallelujah! we rejoice with you.",
    "amen! thank you for sharing. god's power is still at work!",
    "god bless you for your heart to give!",
    "amen! thank you for your generosity.",
    "the lord loves a cheerful giver!",
    "to give your offering or sow a seed online",
    "our church address:",
)


def is_bot_reply_text(text):

    normalized = normalize_message(text)

    return any(
        signature in normalized
        for signature in BOT_REPLY_SIGNATURES
    )


get_bot_channel_identity()


# =============================================================================
# 5. GOOGLE SHEETS SETUP
# =============================================================================

def ensure_sheet_exists(title):

    try:
        metadata = sheets_service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID,
            fields="sheets.properties.title",
        ).execute()

        existing_titles = {
            sheet["properties"]["title"]
            for sheet in metadata.get("sheets", [])
        }

        if title not in existing_titles:

            print(f"[SHEETS] Creating sheet: {title}")

            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {"title": title}
                            }
                        }
                    ]
                },
            ).execute()

    except Exception as e:
        print(
            f"[SHEETS ERROR] Could not ensure sheet '{title}':",
            repr(e)
        )
        raise


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
        maxResults=5,
    ).execute()

    active_broadcasts = broadcast_response.get("items", [])

    if not active_broadcasts:
        print("No active YouTube live broadcast found.")
        sys.exit(1)

    live_chat_id = (
        active_broadcasts[0]
        .get("snippet", {})
        .get("liveChatId")
    )

    if not live_chat_id:
        print("ERROR: Active broadcast has no liveChatId.")
        sys.exit(1)

    print("[YOUTUBE] Connected to active Live Chat.")

except HttpError as e:
    print("[YOUTUBE ERROR] Could not connect:", e)
    sys.exit(1)


# =============================================================================
# 7. GENERAL UTILITIES
# =============================================================================

def remove_emojis(text):

    return "".join(
        char
        for char in str(text)
        if not unicodedata.category(char).startswith("So")
    )


def format_mention(name):

    clean_name = remove_emojis(name).strip()
    clean_name = clean_name.lstrip("@").strip()

    return f"@{clean_name}" if clean_name else ""


def timestamp():

    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


def extract_amount(text):

    match = re.search(
        r"(?:rs\.?|inr|rupees?)?\s*(\d[\d,]*(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )

    return (
        match.group(1).replace(",", "")
        if match else "Not specified"
    )


# =============================================================================
# 8. SEND YOUTUBE CHAT REPLIES
# =============================================================================

def send_message(text):

    global last_send_time

    try:

        elapsed = time.monotonic() - last_send_time

        if elapsed < SEND_INTERVAL_SECONDS:
            time.sleep(SEND_INTERVAL_SECONDS - elapsed)

        response = youtube.liveChatMessages().insert(
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

        sent_id = response.get("id")

        remember_self_message(sent_id)

        last_send_time = time.monotonic()

        print("[SENT]", text, "| message ID:", sent_id)

    except HttpError as e:
        print("[YOUTUBE SEND ERROR]", e)

    except Exception as e:
        print("[SEND ERROR]", repr(e))


# =============================================================================
# 9. GOOGLE SHEETS WRITE FUNCTIONS
# =============================================================================

def append_rows(sheet_name, values):

    if not values:
        return False

    try:

        last_column = chr(ord("A") + len(values[0]) - 1)

        result = sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!A:{last_column}",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()

        print(
            f"[SHEETS SUCCESS] {sheet_name}: "
            f"{result.get('updates', {}).get('updatedRows', 0)} row(s) appended."
        )

        return True

    except Exception as e:

        print(
            f"[SHEETS ERROR] Failed writing to '{sheet_name}':",
            repr(e)
        )

        return False


def add_prayer_request(name, message):

    name = str(name).strip()
    message = remove_emojis(message).strip()

    if not name or not message:
        print("[PRAYER NOT SAVED] Missing viewer name or message.")
        return False

    return append_rows(
        SHEET_NAME,
        [[timestamp(), name, message]],
    )


def add_testimony(name, message):

    name = str(name).strip()
    message = remove_emojis(message).strip()

    if not name or not message:
        print("[TESTIMONY NOT SAVED] Missing viewer name or message.")
        return False

    return append_rows(
        TESTIMONY_SHEET_NAME,
        [[timestamp(), name, message]],
    )


def add_offering(name, message, amount):

    name = str(name).strip()
    message = remove_emojis(message).strip()

    if not name or not message:
        print("[OFFERING NOT SAVED] Missing viewer name or message.")
        return False

    return append_rows(
        OFFERING_SHEET_NAME,
        [[timestamp(), name, message, amount]],
    )


# =============================================================================
# 10. MESSAGE DETECTION
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

    lowered = text.casefold()

    return any(keyword in lowered for keyword in keywords)


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

    lowered = text.casefold()

    return any(keyword in lowered for keyword in keywords)


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

    lowered = text.casefold()

    return any(keyword in lowered for keyword in keywords)


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

    lowered = text.casefold()

    return any(
        re.search(pattern, lowered)
        for pattern in patterns
    )


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

    lowered = text.casefold()

    return any(keyword in lowered for keyword in keywords)


# =============================================================================
# 11. REPLY TEMPLATES
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

ADDRESS_REPLY = f"{{mention}} Our church address: {CHURCH_ADDRESS}"


# =============================================================================
# 12. COOLDOWN
# =============================================================================

def is_on_cooldown(author_key, category):

    key = (author_key, category)
    previous = last_replies.get(key)

    if previous is not None:

        if time.monotonic() - previous < REPLY_COOLDOWN_SECONDS:

            print(
                f"[COOLDOWN] Skipping {category} from {author_key}"
            )

            return True

    return False


def record_reply(author_key, category):

    last_replies[(author_key, category)] = time.monotonic()


# =============================================================================
# 13. PROCESS ONE CHAT MESSAGE
# =============================================================================

def process_message(message):

    message_id = message.get("id")
    snippet = message.get("snippet", {})
    author_details = message.get("authorDetails", {})

    if not message_id:
        print("[SKIPPED] Message without ID.")
        return

    # FILTER 1: Our own sent message IDs.
    if message_id in SELF_SENT_MESSAGE_IDS:

        print("[SKIPPED] Own sent message:", message_id)
        return

    # FILTER 2: Channel owner / authenticated bot identity.
    if is_bot_message(author_details):

        print("[SKIPPED] Own/channel-owner message:", message_id)
        return

    # Only normal text chat messages.
    if snippet.get("type") != "textMessageEvent":
        return

    raw_text = snippet.get("displayMessage", "")
    text = remove_emojis(raw_text).strip()

    if not text:
        return

    # FILTER 3: Known bot reply templates.
    if is_bot_reply_text(text):

        print("[SKIPPED] Bot reply text detected:", text)
        return

    # Retrieve viewer name.
    author = remove_emojis(
        author_details.get("displayName", "")
    ).strip().lstrip("@").strip()

    channel_id = author_details.get("channelId", "").strip()

    if not author and channel_id:
        author = channel_id

    if not author:

        print(
            "[SKIPPED] Missing viewer identity:",
            message_id
        )

        return

    mention = format_mention(author)

    author_key = channel_id or normalize_author(author)

    print(f"[VIEWER MESSAGE] {author}: {text}")

    # PRAYER REQUEST
    if is_prayer_request(text):

        category = "prayer"

        if is_on_cooldown(author_key, category):
            return

        print("[PRAYER REQUEST]", author, text)

        saved = add_prayer_request(author, text)

        if saved:

            reply = random.choice(PRAYER_REPLIES).format(
                mention=mention
            )

            send_message(reply)
            record_reply(author_key, category)

        else:

            print(
                "[PRAYER] Not replying because request was not saved."
            )

    # TESTIMONY
    elif is_testimony(text):

        category = "testimony"

        if is_on_cooldown(author_key, category):
            return

        print("[TESTIMONY]", author, text)

        saved = add_testimony(author, text)

        if saved:

            reply = random.choice(TESTIMONY_REPLIES).format(
                mention=mention
            )

            send_message(reply)
            record_reply(author_key, category)

    # GIVING QUESTION
    elif is_giving_question(text):

        category = "giving_question"

        if is_on_cooldown(author_key, category):
            return

        print("[HOW-TO-GIVE]", author, text)

        send_message(
            GIVING_QUESTION_REPLY.format(mention=mention)
        )

        record_reply(author_key, category)

    # OFFERING
    elif is_offering(text):

        category = "offering"

        if is_on_cooldown(author_key, category):
            return

        print("[OFFERING]", author, text)

        amount = extract_amount(text)

        saved = add_offering(author, text, amount)

        if saved:

            reply = random.choice(OFFERING_REPLIES).format(
                mention=mention
            )

            send_message(reply)
            record_reply(author_key, category)

    # CHURCH ADDRESS
    elif is_address_request(text):

        category = "address"

        if is_on_cooldown(author_key, category):
            return

        print("[ADDRESS]", author, text)

        send_message(
            ADDRESS_REPLY.format(mention=mention)
        )

        record_reply(author_key, category)


# =============================================================================
# 14. MAIN LOOP — READ YOUTUBE LIVE CHAT
# =============================================================================

print("=" * 68)
print("YOUTUBE LIVE CHAT BOT STARTED")
print("=" * 68)

print("Prayer sheet:", SHEET_NAME)
print("Testimony sheet:", TESTIMONY_SHEET_NAME)
print("Offering sheet:", OFFERING_SHEET_NAME)

print(
    "Bot channel IDs:",
    BOT_CHANNEL_IDS or "Not available — backup filters active"
)

next_page_token = None
processed_message_ids = OrderedDict()

while time.time() - START_TIME < MAX_RUNTIME:

    try:

        chat_response = youtube.liveChatMessages().list(
            liveChatId=live_chat_id,
            part="snippet,authorDetails",
            pageToken=next_page_token,
            maxResults=200,
        ).execute()

        messages = chat_response.get("items", [])

        for message in messages:

            message_id = message.get("id")

            if not message_id:
                continue

            if message_id in processed_message_ids:
                continue

            processed_message_ids[message_id] = True

            while len(processed_message_ids) > MAX_TRACKED_IDS:
                processed_message_ids.popitem(last=False)

            process_message(message)

        next_page_token = chat_response.get("nextPageToken")

        polling_interval = (
            chat_response.get("pollingIntervalMillis", 5000) / 1000
        )

        time.sleep(max(1, polling_interval))

    except HttpError as e:

        print("[YOUTUBE API ERROR]", e)
        time.sleep(5)

    except google.auth.exceptions.TransportError as e:

        print("[TRANSPORT ERROR]", e)
        time.sleep(10)

    except google.auth.exceptions.RefreshError as e:

        print("[TOKEN ERROR]", e)
        sys.exit(1)

    except KeyboardInterrupt:

        print("Bot stopped manually.")
        break

    except Exception as e:

        print("[UNEXPECTED ERROR]", repr(e))
        time.sleep(5)


print("=" * 68)
print("BOT EXECUTION COMPLETED")
print("=" * 68)
