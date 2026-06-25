#!/usr/bin/env python3
"""Comment monitor (Claude + Figma stack) — detect NEW comments on your recent posts,
reply publicly + DM the commenter. State in content/metrics/handled_comments.json
so we never respond twice.

Run with the repo venv: .venv/bin/python scripts/comment_monitor.py <cmd>

  auto                 HEADLESS: for each new comment, match it to a rule in
                       content/metrics/auto_responses.json → reply (link-free) + DM;
                       anything with no matching rule is DEFERRED for human review.
                       This is what launchd runs every 15 min.
  review               print comments that were DEFERRED (need a human)
  seed                 mark all CURRENT comments handled (no responses) — run once at setup
  scan                 print NEW (unhandled, not ours) comments as JSON
  send <cid> --reply "..." [--dm "..."]   manual: public-reply + optional DM + mark handled
  mark <cid>           mark a comment handled without responding (skip it)
"""
import os, sys, json, argparse, traceback, datetime
from pathlib import Path
from dotenv import load_dotenv

# ROOT is portable: env override (cloud) → else two levels up from this file (scripts/..)
ROOT = Path(os.environ["OOTTO_ROOT"]) if os.environ.get("OOTTO_ROOT") else Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")          # local: loads .env; cloud: no-op (env comes from GitHub secrets)
from composio import Composio

c = Composio(api_key=os.environ["COMPOSIO_API_KEY"])
USER = os.getenv("USER_ID", "ootto")
CONN = os.getenv("CONNECTED_ACCOUNT_ID")
IG   = os.environ["IG_BUSINESS_ACCOUNT_ID"]
OUR_HANDLE = os.getenv("IG_HANDLE", "").lower()   # YOUR handle — never reply to your own comments
METRICS = ROOT / "content" / "metrics"
STATE   = METRICS / "handled_comments.json"
RULES   = METRICS / "auto_responses.json"
LOG     = METRICS / "monitor.log"
RECENT_MEDIA = 8                            # how many recent posts to scan

def now():
    # launchd-safe timestamp (Date.now is fine in plain python)
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(msg):
    METRICS.mkdir(parents=True, exist_ok=True)
    line = f"[{now()}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def asd(r):
    if isinstance(r, dict): return r
    for m in ("model_dump", "dict"):
        if hasattr(r, m):
            try: return getattr(r, m)()
            except Exception: pass
    return getattr(r, "__dict__", {"_repr": str(r)})

def run(slug, args):
    return asd(c.tools.execute(slug, arguments=args, user_id=USER,
                               connected_account_id=CONN,
                               dangerously_skip_version_check=True))

def data_of(r):
    d = r.get("data", r) if isinstance(r, dict) else r
    if isinstance(d, dict):
        d = d.get("data") or d.get("media") or d.get("comments") \
            or d.get("response_data", {}).get("data") or []
    return d if isinstance(d, list) else []

def paged(slug, args, item_cap=3000):
    """Follow `after` cursors across ALL pages — data_of() alone drops the cursor,
    so endpoints with >1 page (e.g. a reel with >25 comments) silently lose the rest.
    Only the `after` param advances paging for these IG tools."""
    out, seen, after = [], set(), None
    while len(out) < item_cap:
        a = dict(args)
        if after:
            a["after"] = after
        r = run(slug, a)
        d = r.get("data", {}) if isinstance(r, dict) else {}
        items = d.get("data") if isinstance(d, dict) else None
        out.extend(items if isinstance(items, list) else data_of(r))
        pg = d.get("paging", {}) if isinstance(d, dict) else {}
        cur = (pg.get("cursors") or {}).get("after")
        if not pg.get("next") or not cur or cur in seen:
            break
        seen.add(cur); after = cur
    return out

def load_state():
    if STATE.exists():
        try:
            s = json.loads(STATE.read_text())
            s.setdefault("handled", []); s.setdefault("deferred", []); s.setdefault("dm_handled", [])
            return s
        except Exception: pass
    return {"handled": [], "deferred": [], "dm_handled": []}

def save_state(s):
    METRICS.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2))

def load_rules():
    if RULES.exists():
        try: return json.loads(RULES.read_text())
        except Exception: pass
    return {"rules": [], "default": "defer"}

def all_comments():
    """Return [{id, username, text, media_id, caption}] across recent media."""
    out = []
    media = data_of(run("INSTAGRAM_GET_IG_USER_MEDIA", {"ig_user_id": IG}))[:RECENT_MEDIA]
    for m in media:
        mid = m.get("id"); cap = (m.get("caption") or "")[:120].replace("\n", " ")
        for cm in paged("INSTAGRAM_GET_IG_MEDIA_COMMENTS", {"ig_media_id": mid}):
            u = cm.get("username") or (cm.get("from") or {}).get("username") or "?"
            out.append({"id": cm.get("id"), "username": u,
                        "text": cm.get("text", ""), "media_id": mid, "caption": cap})
    return out

def new_comments():
    s = load_state(); handled = set(s.get("handled", []))
    return [cm for cm in all_comments()
            if cm["id"] and cm["id"] not in handled
            and cm["username"].lower() != OUR_HANDLE]

def do_send(cid, reply, dm):
    res = {"comment_id": cid}
    if reply:
        r = run("INSTAGRAM_REPLY_TO_COMMENT", {"ig_comment_id": cid, "message": reply})
        res["reply_ok"] = bool(r.get("successful"))
    if dm:
        r = asd(c.tools.proxy(endpoint=f"/{IG}/messages", method="POST",
                body={"recipient": {"comment_id": cid}, "message": {"text": dm}},
                connected_account_id=CONN))
        d = r.get("data", {}) if isinstance(r, dict) else {}
        res["dm_ok"]  = (r.get("status") == 200 and bool(d.get("message_id"))) if isinstance(r, dict) else False
        res["dm_err"] = (d.get("error") or {}).get("message") if isinstance(d, dict) else None
    s = load_state()                       # always mark handled so we never retry/spam
    if cid not in s["handled"]:
        s["handled"].append(cid); save_state(s)
    return res

def lst(r):
    d = r.get("data", r) if isinstance(r, dict) else r
    if isinstance(d, dict):
        d = d.get("data") or d.get("conversations") or d.get("messages") or []
    return d if isinstance(d, list) else []

def all_conversations():
    """Latest message per DM thread: [{conv_id, msg_id, from_id, from_user, text, ts}]."""
    out = []
    for cv in paged("INSTAGRAM_LIST_ALL_CONVERSATIONS", {"ig_user_id": IG}):
        cid = cv.get("id")
        if not cid: continue
        msgs = lst(run("INSTAGRAM_LIST_ALL_MESSAGES", {"conversation_id": cid}))
        if not msgs: continue
        latest = msgs[0]; frm = latest.get("from") or {}
        out.append({"conv_id": cid, "msg_id": latest.get("id"),
                    "from_id": frm.get("id"), "from_user": frm.get("username", "?"),
                    "text": latest.get("message", ""), "ts": latest.get("created_time")})
    return out

def new_dms():
    s = load_state(); handled = set(s.get("dm_handled", []))
    return [cv for cv in all_conversations()
            if cv["msg_id"] and cv["msg_id"] not in handled
            and (cv["from_user"] or "").lower() != OUR_HANDLE]

def send_dm(to_id, text):
    r = asd(c.tools.proxy(endpoint=f"/{IG}/messages", method="POST",
            body={"recipient": {"id": to_id}, "message": {"text": text}},
            connected_account_id=CONN))
    d = r.get("data", {}) if isinstance(r, dict) else {}
    return {"ok": (r.get("status") == 200 and bool(d.get("message_id"))) if isinstance(r, dict) else False,
            "err": (d.get("error") or {}).get("message") if isinstance(d, dict) else None}

def match_text_rule(text, rules):
    t = (text or "").lower()
    for rule in rules:
        if any(k.lower() in t for k in (rule.get("match_text") or [])):
            return rule
    return None

def match_rule(cm, rules):
    cap = (cm.get("caption") or "").lower()
    txt = (cm.get("text") or "").lower()
    mid = cm.get("media_id")
    for rule in rules:
        if mid and mid in (rule.get("match_media_id") or []):           return rule
        if any(k.lower() in cap for k in (rule.get("match_caption") or [])): return rule
        if any(k.lower() in txt for k in (rule.get("match_text") or [])):    return rule
    return None

# ---------------- commands ----------------
def cmd_seed():
    s = load_state()
    ids = {cm["id"] for cm in all_comments() if cm["id"]}
    s["handled"] = sorted(set(s.get("handled", [])) | ids)
    try:
        dm_ids = {cv["msg_id"] for cv in all_conversations() if cv["msg_id"]}
        s["dm_handled"] = sorted(set(s.get("dm_handled", [])) | dm_ids)
    except Exception as e:
        dm_ids = set(); log(f"seed: DM list failed ({e})")
    save_state(s)
    log(f"seeded {len(ids)} comments + {len(dm_ids)} DM threads as handled "
        f"(handled={len(s['handled'])}, dm_handled={len(s['dm_handled'])})")

def cmd_scan():
    new = new_comments()
    print(json.dumps(new, indent=2, ensure_ascii=False))
    print(f"\n# {len(new)} new comment(s)", file=sys.stderr)

def cmd_auto():
    cfg = load_rules()
    rules = cfg.get("rules", [])
    # ---- comments ----
    try:
        new = new_comments()
    except Exception as e:
        log(f"AUTO comment-scan FAILED: {e}"); new = []
    s = load_state()
    for cm in new:
        cid = cm["id"]; u = cm["username"]; t = cm["text"][:60]
        try:
            rule = match_rule(cm, rules)
            if rule:
                res = do_send(cid, rule.get("reply", ""), rule.get("dm", ""))
                log(f"RESPONDED @{u} «{t}» rule={rule.get('name')} "
                    f"reply_ok={res.get('reply_ok')} dm_ok={res.get('dm_ok')} dm_err={res.get('dm_err')}")
            else:
                if cid not in s["deferred"]:
                    s["deferred"].append(cid); save_state(s)
                log(f"DEFERRED @{u} «{t}» (no rule) → run `comment_monitor.py review`")
        except Exception:
            log(f"ERROR on comment {cid} @{u}: {traceback.format_exc().splitlines()[-1]}")
    # ---- incoming DMs ----
    dm_rules = cfg.get("dm_rules", []); dm_default = cfg.get("dm_default", "")
    try:
        dms = new_dms()
    except Exception as e:
        log(f"AUTO dm-scan FAILED: {e}"); dms = []
    for dm in dms:
        u = dm["from_user"]; t = (dm["text"] or "")[:50]; mid = dm["msg_id"]
        try:
            rule = match_text_rule(dm["text"], dm_rules)
            msg = rule.get("dm") if rule else dm_default
            res = send_dm(dm["from_id"], msg) if (msg and dm["from_id"]) else {"ok": False, "err": "no msg/id"}
            st = load_state()                       # mark handled regardless (don't retry window-closed forever)
            if mid not in st["dm_handled"]:
                st["dm_handled"].append(mid); save_state(st)
            tag = "DM_SENT" if res["ok"] else "DM_SKIP"
            log(f"{tag} @{u} «{t}» rule={rule.get('name') if rule else 'default'} ok={res['ok']} err={res['err']}")
        except Exception:
            log(f"ERROR on dm {mid} @{u}: {traceback.format_exc().splitlines()[-1]}")

def cmd_review():
    s = load_state(); deferred = set(s.get("deferred", []))
    rows = [cm for cm in all_comments() if cm["id"] in deferred]
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    print(f"\n# {len(rows)} comment(s) awaiting human review", file=sys.stderr)

def cmd_mark(cid):
    s = load_state()
    if cid not in s["handled"]:
        s["handled"].append(cid)
    if cid in s.get("deferred", []):
        s["deferred"].remove(cid)
    save_state(s)
    print(f"marked {cid} handled")

def cmd_send(cid, reply, dm):
    print(json.dumps(do_send(cid, reply, dm), ensure_ascii=False))

def cmd_scandm():
    new = new_dms()
    print(json.dumps(new, indent=2, ensure_ascii=False))
    print(f"\n# {len(new)} new DM(s)", file=sys.stderr)

def cmd_senddm(from_id, msg_id, text):
    res = send_dm(from_id, text)
    s = load_state()
    if msg_id not in s["dm_handled"]:
        s["dm_handled"].append(msg_id); save_state(s)
    print(json.dumps({"from_id": from_id, "msg_id": msg_id, **res}, ensure_ascii=False))

def cmd_markdm(msg_id):
    s = load_state()
    if msg_id not in s["dm_handled"]:
        s["dm_handled"].append(msg_id); save_state(s)
    print(f"marked DM {msg_id} handled")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if   cmd == "auto":   cmd_auto()
    elif cmd == "review": cmd_review()
    elif cmd == "seed":   cmd_seed()
    elif cmd == "scan":   cmd_scan()
    elif cmd == "scandm": cmd_scandm()
    elif cmd == "mark":   cmd_mark(sys.argv[2])
    elif cmd == "markdm": cmd_markdm(sys.argv[2])
    elif cmd == "send":
        p = argparse.ArgumentParser()
        p.add_argument("cid"); p.add_argument("--reply", default=""); p.add_argument("--dm", default="")
        a = p.parse_args(sys.argv[2:]); cmd_send(a.cid, a.reply, a.dm)
    elif cmd == "senddm":
        p = argparse.ArgumentParser()
        p.add_argument("from_id"); p.add_argument("msg_id"); p.add_argument("--text", required=True)
        a = p.parse_args(sys.argv[2:]); cmd_senddm(a.from_id, a.msg_id, a.text)
    else:
        print(__doc__); sys.exit(1)
