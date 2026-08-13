# Claude + Figma stack

> Design in **Figma**, let **Claude** build the reel, post it, and reply to every lead — on autopilot.

This is the exact stack behind [@jayantcreates.ai](https://instagram.com/jayantcreates.ai): a faceless
Instagram page where Claude finds what's working, builds the finished reel, posts it 3× a day, and DMs
every commenter the resource. It's four pieces you can wire up in an afternoon — all free except your own
Instagram + an AI posting key.

```
 Figma (design + Motion)  ──▶  Claude (reads design, writes the reel)  ──▶  Post 3×/day  ──▶  Reply + DM every lead
        plugin                     content skills                          Composio          this repo's GitHub Action
```

---

## What you get

| Piece | What it does | Cost |
|---|---|---|
| **1. Figma ↔ Claude plugin** | Claude reads your Figma file + design tokens and writes code / canvas. Figma **Motion** (shipped at Config 2026) gives you a real video timeline on the canvas. | Free |
| **2. Content skills** | Claude turns a viral reel into *your own* original — finds the format, writes the hook + script, builds the finished reel (voiceover, captions, animation). | Free |
| **3. Posting** | Publishes the reel to Instagram on a schedule (3× a day) via the Instagram Graph API. | Free API + your IG |
| **4. Lead automation** *(this repo)* | A GitHub Action watches your comments — every keyword match gets a public reply **and** a DM with the resource. Runs in the cloud, even with your laptop off. | Free |

> **Honest note:** Figma's own AI builds the Motion keyframes. Claude's job is design → code and the
> content loop (find → script → build → post → reply). Together they're a workflow, not magic.

---

## Setup

### 1 — Connect Figma to Claude
```bash
claude plugin install figma@claude-plugins-official
```
Now Claude can read your Figma designs + tokens and write the code. Open Figma, try **Motion** (the new
timeline on the canvas) to animate, then ask Claude to turn the frames into a reel.

### 2 — Get the content skills
```bash
/plugin marketplace add Ootto-AI/claude-content-skills
```
8 free, MIT-licensed Claude skills: `reel-analyzer` (Claude watches a viral reel + breaks it down),
`viral-hook-writer`, `reel-scripter`, `reel-builder` (builds the finished reel), `caption-and-hashtags`,
`ai-brain` (brand memory) + `content-repurposer` & `content-calendar`. Browse:
<https://github.com/Ootto-AI/claude-content-skills>

### 3 — Wire posting (Composio + Instagram)
You need an Instagram **Business/Creator** account and a [Composio](https://composio.dev) key (it wraps the
Instagram Graph API so Claude can publish). Copy `.env.example` → `.env` and fill it in:
```bash
cp .env.example .env
```
```
COMPOSIO_API_KEY=…
IG_BUSINESS_ACCOUNT_ID=…     # your IG business account id
CONNECTED_ACCOUNT_ID=…       # the Composio connected-account id
USER_ID=…                    # your Composio user id
IG_HANDLE=yourhandle         # so the bot never replies to your own comments
```

### 4 — Turn on the lead automation (this repo)
The included GitHub Action (`.github/workflows/lead-monitor.yml`) runs every 20 minutes, finds new
comments on your recent posts, and for each one matches a rule in
[`content/metrics/auto_responses.json`](content/metrics/auto_responses.json):

- **public reply** — a short, **link-free** acknowledgement ("just sent it to your DMs 📩")
- **DM** — the actual resource / link (Instagram only allows links in DMs, not public replies)

**To enable it on a fork:**
1. Fork this repo.
2. **Settings → Secrets and variables → Actions** → add `COMPOSIO_API_KEY`, `IG_BUSINESS_ACCOUNT_ID`,
   `CONNECTED_ACCOUNT_ID`, `USER_ID`, `IG_HANDLE`.
3. **Actions** tab → enable workflows.
4. Run once locally to mark existing comments as handled (so it doesn't reply to old ones):
   ```bash
   pip install -r requirements.txt
   python scripts/comment_monitor.py seed
   ```
5. Edit `content/metrics/auto_responses.json` — add a rule for each post's keyword (see below).

---

## Writing reply rules

Each reel with a "comment WORD → I'll DM it" CTA gets one rule. First match wins; no match → deferred for
a human. Example:

```jsonc
{
  "rules": [
    {
      "name": "stack",
      "match_text": ["stack"],              // fires when a comment contains "stack"
      "match_media_id": ["1808…"],          // (optional) only on this post
      "reply": "🙌 just sent it to your DMs — check 📩",   // PUBLIC — never a link
      "dm": "Here's the Claude + Figma stack 🙌 …"          // DM — the link/resource lives here
    }
  ]
}
```

**Rule of the house:** the public reply **never** contains a link — the link goes in the DM only. (Instagram
suppresses reach on comments with links, and it keeps the lead in your inbox.)

---

## Commands (run locally)

```bash
python scripts/comment_monitor.py seed     # mark all current comments handled (run once at setup)
python scripts/comment_monitor.py auto     # the headless loop the Action runs (reply + DM by rule)
python scripts/comment_monitor.py review   # show comments with no matching rule (need a human)
python scripts/comment_monitor.py scan     # print new, unhandled comments as JSON
python scripts/comment_monitor.py send <comment_id> --reply "…" --dm "…"   # manual one-off
```

---

## How the daily loop runs (with Claude)

1. **Find** — `reel-analyzer` watches a currently-viral reel in your niche, frame by frame.
2. **Write** — `viral-hook-writer` + `reel-scripter` write an original hook + script in your voice.
3. **Design** — build/adjust the look in **Figma** (use Motion for any animated beats); Claude reads it.
4. **Build** — `reel-builder` renders the finished reel (voiceover, captions, animation).
5. **Approve** — you hit yes (keep a human in the loop until you trust it).
6. **Post** — Composio publishes it; rotate 3× a day.
7. **Reply** — this repo's Action replies + DMs every lead, around the clock.

---

## License

MIT — see [LICENSE](LICENSE). Built by [Ootto](https://instagram.com/jayantcreates.ai). PRs welcome.

---

Built by **[Ootto](https://ootto.ai)** - the 24/7 AI operator for Instagram. It studies what is working in your niche, writes and renders the reels, posts them, and turns the comments into leads. [See it running](https://ootto.ai/content).
