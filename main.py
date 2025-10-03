# Bluesky autoposter from Google Sheets (TSV/CSV)
# - Uses BLUESKY_USERNAME (or BLUESKY_HANDLE) + BLUESKY_APP_PASSWORD
# - Robust parsing, threading, link cards, gallery embeds, headless fallback

import os, io, re, time, json
import requests
import pandas as pd
from datetime import datetime
from dateutil import tz
from atproto import Client, models

# ---------- CONFIG & ENV ----------
BLSKY_USER = (
    os.getenv("BLUESKY_USERNAME")
    or os.getenv("BLUESKY_HANDLE")
)  # your handle like "proustalia.bsky.social"
BLSKY_PASS = os.getenv("BLUESKY_APP_PASSWORD")  # app password abcd-efgh-ijkl-mnop
SHEET_CSV_URL = os.getenv("SHEET_CSV_URL")      # recommend format=tsv
LOCAL_TZ = tz.gettz(os.getenv("TIMEZONE", "UTC"))
POLL_SECS = int(os.getenv("POLL_SECONDS", "600"))
STATE_FILE = "state.json"

# Sheet columns
COL_THREAD = "Thread ID"
COL_SEQ    = "Sequence"
COL_TEXT   = "Post Text"
IMG_COLS   = ["Image 1 URL","Image 2 URL","Image 3 URL","Image 4 URL"]
ALT_COLS   = ["Alt Text 1","Alt Text 2","Alt Text 3","Alt Text 4"]
COL_IMG1_TITLE = "Image 1 Title"  # optional, fallback title for solo-image card
COL_LINK_URL   = "Link URL"
COL_LINK_TITLE = "Link Title"
COL_LINK_DESC  = "Link Description"
COL_LINK_THUMB = "Link Thumb URL"
COL_TIME  = "Scheduled Time"   # supports :SS or no seconds
COL_DELAY = "Delay (sec)"
COL_STATUS= "Status"           # Scheduled / Draft / Posted

# Thread fallback: if no row has Sequence=1, promote smallest sequence to head
HEADLESS_FALLBACK = True

# ---------- HELPERS ----------
def now_local():
    return datetime.now(LOCAL_TZ)

def parse_time(s):
    if not isinstance(s, str) or not s.strip():
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=LOCAL_TZ)
        except ValueError:
            pass
    print(f"[warn] Could not parse time: {s}")
    return None

def norm_tid(s):
    return re.sub(r"\s+", " ", (s or "").strip())

def seq_int(v, default=0):
    m = re.search(r"-?\d+", str(v) if v is not None else "")
    return int(m.group()) if m else default

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"posted_keys": []}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def row_key(row):
    tid  = str(row.get(COL_THREAD, "")).strip()
    seq  = str(row.get(COL_SEQ, "")).strip()
    tim  = str(row.get(COL_TIME, "")).strip()
    head = str(row.get(COL_TEXT, "")).strip()[:24]
    return f"{tid}|{seq}|{tim}|{head}"

def fetch_sheet():
    r = requests.get(SHEET_CSV_URL, timeout=30)
    r.raise_for_status()
    sep = "\t" if "format=tsv" in SHEET_CSV_URL.lower() else ","
    df = pd.read_csv(
        io.StringIO(r.text),
        sep=sep,
        engine="python",
        dtype=str,
        keep_default_na=False,
        quoting=3,          # QUOTE_NONE
        on_bad_lines="skip"
    )
    df.columns = [c.strip() for c in df.columns]
    return df

def upload_blob(client: Client, url: str):
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        resp = requests.get(url.strip(), timeout=60)
        resp.raise_for_status()
        return client.upload_blob(resp.content).blob
    except Exception as e:
        print(f"[warn] blob upload failed: {url} -> {e}")
        return None

def image_urls(row):
    return [u for u in [str(row.get(c, "") or "").strip() for c in IMG_COLS] if u]

def make_external_embed(client, url, title, desc="", thumb_url=None, fallback_thumb=None):
    thumb_blob = None
    if thumb_url:
        thumb_blob = upload_blob(client, thumb_url)
    if not thumb_blob and fallback_thumb:
        thumb_blob = upload_blob(client, fallback_thumb)
    ext = models.AppBskyEmbedExternal.External(
        uri=url, title=title or "", description=desc or "", thumb=thumb_blob
    )
    return models.AppBskyEmbedExternal.Main(external=ext)

def build_embed_for_row(client, row):
    # 1) Explicit Link URL → card
    link_url = str(row.get(COL_LINK_URL, "") or "").strip()
    if link_url:
        title = str(row.get(COL_LINK_TITLE, "") or "").strip()
        if not title:
            title = str(row.get(COL_IMG1_TITLE, "") or row.get(ALT_COLS[0], "") or "").strip()
        desc  = str(row.get(COL_LINK_DESC, "") or "").strip()
        thumb = str(row.get(COL_LINK_THUMB, "") or "").strip()
        imgs  = image_urls(row)
        fall  = imgs[0] if len(imgs) == 1 else None
        return make_external_embed(client, link_url, title, desc, thumb, fall)

    # 2) Exactly one image → link card to that image URL (title from title/alt)
    imgs = image_urls(row)
    if len(imgs) == 1:
        title = str(row.get(COL_LINK_TITLE, "") or row.get(COL_IMG1_TITLE, "") or row.get(ALT_COLS[0], "") or "").strip()
        return make_external_embed(client, imgs[0], title, "", None, imgs[0])

    # 3) 2–4 images → gallery
    if 2 <= len(imgs) <= 4:
        images = []
        for i in range(4):
            url = str(row.get(IMG_COLS[i], "") or "").strip()
            if url:
                blob = upload_blob(client, url)
                if blob:
                    alt = str(row.get(ALT_COLS[i], "") or "")
                    images.append(models.AppBskyEmbedImages.Image(alt=alt, image=blob))
        if images:
            return models.AppBskyEmbedImages.Main(images=images)

    return None

def post_single(client, text, embed=None, reply_ref=None):
    # High-level helper; returns strong ref for threading
    res = client.send_post(text=text, embed=embed, reply_to=reply_ref)
    return models.create_strong_ref(res)

def post_thread(client, group_rows):
    root_ref = None
    for idx, row in enumerate(group_rows):
        text  = str(row.get(COL_TEXT, "") or "")
        embed = build_embed_for_row(client, row)
        ref   = post_single(client, text, embed, root_ref if idx > 0 else None)
        if root_ref is None:
            root_ref = ref
        try:
            delay = int(row.get(COL_DELAY, 5))
        except Exception:
            delay = 5
        if idx < len(group_rows) - 1 and delay > 0:
            time.sleep(delay)
    return True

# ---------- MAIN LOOP ----------
def run_loop():
    assert BLSKY_USER and BLSKY_PASS and SHEET_CSV_URL, "Missing BLUESKY_USERNAME/BLUESKY_HANDLE, BLUESKY_APP_PASSWORD, or SHEET_CSV_URL"
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
            for c in [COL_THREAD, COL_SEQ, COL_TEXT, COL_TIME, COL_DELAY, COL_STATUS,
                      COL_LINK_URL, COL_LINK_TITLE, COL_LINK_DESC, COL_LINK_THUMB, COL_IMG1_TITLE] + IMG_COLS + ALT_COLS:
                if c not in df.columns:
                    df[c] = ""

            # normalize thread + seq for all rows and group
            records = df.to_dict("records")
            by_thread = {}
            for r in records:
                r[COL_THREAD] = norm_tid(r.get(COL_THREAD, ""))
                r[COL_SEQ]    = seq_int(r.get(COL_SEQ, 0))
                by_thread.setdefault(r[COL_THREAD], []).append(r)
            for tid in by_thread:
                by_thread[tid].sort(key=lambda x: x[COL_SEQ])

            # due rows not yet posted
            due = []
            for r in records:
                if str(r.get(COL_STATUS, "")).strip().lower() != "scheduled":
                    continue
                t = parse_time(str(r.get(COL_TIME, "")))
                if not t or t > now_local():
                    continue
                key = row_key(r)
                if key not in state["posted_keys"]:
                    due.append(r)

            if not due:
                print("[info] nothing due. Sleeping…")
                time.sleep(POLL_SECS)
                continue

            for r in due:
                k   = row_key(r)
                tid = r.get(COL_THREAD, "")
                seq = r.get(COL_SEQ, 0)

                if tid and seq == 1:
                    grp = by_thread.get(tid, [r])
                    print(f"[info] posting thread {tid} with {len(grp)} posts…")
                    post_thread(client, grp)
                    for gr in grp:
                        gk = row_key(gr)
                        if gk not in state["posted_keys"]:
                            state["posted_keys"].append(gk)
                    save_state(state)

                elif not tid:
                    print(f"[info] posting single: {k}")
                    embed = build_embed_for_row(client, r)
                    post_single(client, str(r.get(COL_TEXT, "") or ""), embed, None)
                    if k not in state["posted_keys"]:
                        state["posted_keys"].append(k)
                    save_state(state)

                else:
                    # non-head row due
                    if HEADLESS_FALLBACK:
                        thread_rows = by_thread.get(tid, [])
                        has_head = any(x.get(COL_SEQ, 0) == 1 for x in thread_rows)
                        if not has_head:
                            print(f"[info] no explicit head for '{tid}'. Promoting smallest-seq row to head…")
                            post_thread(client, thread_rows)
                            for gr in thread_rows:
                                gk = row_key(gr)
                                if gk not in state["posted_keys"]:
                                    state["posted_keys"].append(gk)
                            save_state(state)
                            continue
                    print(f"[info] waiting for thread head before posting: {k}")

            print("[info] cycle complete. Sleeping…")
            time.sleep(POLL_SECS)

        except Exception as e:
            print("[error]", e)
            time.sleep(POLL_SECS)

if __name__ == "__main__":
    run_loop()