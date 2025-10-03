# Bluesky autoposter from Google Sheets (CSV)
# - Posts rows where Status = Scheduled and Scheduled Time <= now (local tz)
# - Supports threads (Thread ID + Sequence)
# - Up to 4 images per post with alt text
# - Keeps a local state.json so it doesn't double-post

import os, time, json, io
import requests
import pandas as pd
from datetime import datetime
from dateutil import tz
from atproto import Client, models

# ====== CONFIG FROM SECRETS ======
BLSKY_USER = os.getenv("BLUESKY_USERNAME")
BLSKY_PASS = os.getenv("BLUESKY_APP_PASSWORD")
SHEET_CSV_URL = os.getenv("SHEET_CSV_URL")
LOCAL_TZ = tz.gettz(os.getenv("TIMEZONE", "UTC"))
POLL_SECS = int(os.getenv("POLL_SECONDS", "600"))  # every 10 min by default
STATE_FILE = "state.json"

# ====== EXPECTED SHEET COLUMNS ======
COL_THREAD = "Thread ID"
COL_SEQ = "Sequence"
COL_TEXT = "Post Text"
IMG_COLS  = ["Image 1 URL","Image 2 URL","Image 3 URL","Image 4 URL"]
ALT_COLS  = ["Alt Text 1","Alt Text 2","Alt Text 3","Alt Text 4"]
COL_TIME  = "Scheduled Time"   # YYYY-MM-DD HH:MM in your local tz
COL_DELAY = "Delay (sec)"      # pause between thread posts
COL_STATUS= "Status"           # Draft / Scheduled / Posted (bot reads only "Scheduled")

# ====== HELPERS ======
def now_local():
    return datetime.now(LOCAL_TZ)

def parse_time(s):
    if not isinstance(s, str) or not s.strip():
        return None
    dt = datetime.strptime(s.strip(), "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=LOCAL_TZ)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"posted_keys": []}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def row_key(row):
    tid = str(row.get(COL_THREAD, "")).strip()
    seq = str(row.get(COL_SEQ, "")).strip()
    tim = str(row.get(COL_TIME, "")).strip()
    head = str(row.get(COL_TEXT, "")).strip()[:24]
    return f"{tid}|{seq}|{tim}|{head}"

def fetch_sheet():
    r = requests.get(SHEET_CSV_URL, timeout=30)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))

def fetch_image_blob(client: Client, url: str):
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        resp = requests.get(url.strip(), timeout=60)
        resp.raise_for_status()
        blob = client.upload_blob(resp.content)
        return blob.blob
    except Exception as e:
        print(f"[warn] image fetch/upload failed: {url} -> {e}")
        return None

def build_embed_images(client, row):
    images = []
    for i in range(4):
        url = row.get(IMG_COLS[i], "")
        if isinstance(url, str) and url.strip():
            blob = fetch_image_blob(client, url)
            if blob:
                alt = str(row.get(ALT_COLS[i], "") or "")
                images.append(models.AppBskyEmbedImages.Image(alt=alt, image=blob))
    if images:
        return models.AppBskyEmbedImages.Main(images=images)
    return None

def post_single(client, text, images_embed=None, reply_ref=None):
    record = models.AppBskyFeedPost.Main(
        text=text,
        created_at=datetime.utcnow().isoformat() + "Z"
    )
    if images_embed:
        record.embed = images_embed
    if reply_ref:
        record.reply = models.AppBskyFeedPost.ReplyRef(
            parent=reply_ref,
            root=reply_ref.root if hasattr(reply_ref, "root") else reply_ref
        )
    res = client.send_post(record)
    return models.create_strong_ref(res)  # for threading replies

def post_thread(client, group_rows):
    """group_rows must be sorted by Sequence asc"""
    root_ref = None
    for idx, row in enumerate(group_rows):
        text = str(row.get(COL_TEXT, "") or "")
        embed = build_embed_images(client, row)
        ref = post_single(client, text, embed, root_ref if idx > 0 else None)
        if root_ref is None:
            root_ref = ref
        delay = 0
        try:
            delay = int(row.get(COL_DELAY, 5))
        except:
            delay = 5
        if idx < len(group_rows) - 1 and delay > 0:
            time.sleep(delay)
    return True

def due_rows(df):
    out = []
    for _, row in df.iterrows():
        status = str(row.get(COL_STATUS, "")).strip().lower()
        if status != "scheduled":
            continue
        t = parse_time(str(row.get(COL_TIME, "")))
        if t and t <= now_local():
            out.append(row.to_dict())
    return out

# ====== MAIN LOOP ======
def run_loop():
    print("[info] logging in to Bluesky…")
    client = Client()
    client.login(BLSKY_USER, BLSKY_PASS)
    print("[info] logged in as", BLSKY_USER)

    state = load_state()

    while True:
        try:
            print("[info] fetching sheet…")
            df = fetch_sheet()
            # ensure columns exist
            for c in [COL_THREAD, COL_SEQ, COL_TEXT, COL_TIME, COL_DELAY, COL_STATUS] + IMG_COLS + ALT_COLS:
                if c not in df.columns:
                    df[c] = ""

            # list of rows that are due and not already posted
            due = [r.to_dict() for _, r in df.iterrows()
                   if str(r.get(COL_STATUS, "")).strip().lower() == "scheduled"
                   and parse_time(str(r.get(COL_TIME, ""))) is not None
                   and parse_time(str(r.get(COL_TIME, ""))) <= now_local()
                   and row_key(r.to_dict()) not in load_state()["posted_keys"]]

            if not due:
                print("[info] nothing due. Sleeping…")
                time.sleep(POLL_SECS)
                continue

            # group all rows by Thread ID (may be empty)
            all_records = df.to_dict("records")
            threads = {}
            for r in all_records:
                tid = str(r.get(COL_THREAD, "")).strip()
                threads.setdefault(tid, []).append(r)
            for tid in threads:
                # sort each thread by Sequence (empty/NaN -> 0)
                for r in threads[tid]:
                    try:
                        r[COL_SEQ] = int(r.get(COL_SEQ, 0) or 0)
                    except:
                        r[COL_SEQ] = 0
                threads[tid].sort(key=lambda x: x[COL_SEQ])

            # process all due rows
            for r in due:
                k = row_key(r)
                tid = str(r.get(COL_THREAD, "")).strip()
                seq = int(r.get(COL_SEQ, 0) or 0)

                if tid and seq == 1:
                    group = threads.get(tid, [r])
                    print(f"[info] posting thread {tid} with {len(group)} posts…")
                    post_thread(client, group)
                    # mark each row in this thread as posted (local state only)
                    state = load_state()
                    for gr in group:
                        state["posted_keys"].append(row_key(gr))
                    save_state(state)
                elif not tid:
                    print(f"[info] posting single: {k}")
                    embed = build_embed_images(client, r)
                    post_single(client, str(r.get(COL_TEXT, "") or ""), embed, None)
                    state = load_state()
                    state["posted_keys"].append(k)
                    save_state(state)
                else:
                    # A non-seq-1 row is due; skip until seq 1 triggers the thread
                    print(f"[info] waiting for thread head before posting: {k}")

            print("[info] cycle complete. Sleeping…")
            time.sleep(POLL_SECS)

        except Exception as e:
            print("[error]", e)
            time.sleep(POLL_SECS)

if __name__ == "__main__":
    assert BLSKY_USER and BLSKY_PASS and SHEET_CSV_URL, "Missing required secrets."
    run_loop()