#!/usr/bin/env python3
"""
vpn_lead_agent — run from YOUR HOME MACHINE (ExpressVPN ON, residential IP).

Pulls real freelance-hire leads from Reddit (r/forhire, r/freelance, etc.)
+ HN + RemoteOK, classifies CLIENT (🟢 buyer) vs JOB vs NOT-A-CLIENT, and
writes a clean ranked lead list you can sell to vibe-coders at 30%.

WHY THIS WORKS ONLY ON YOUR MACHINE:
  Reddit HTTP-403s every cloud/datacenter IP (Workers, Actions, Render, VPS).
  Your VPN's residential IP is the ONE place Reddit lets through.

USAGE:
  pip install requests
  python3 vpn_lead_agent.py            # one scan, prints leads
  python3 vpn_lead_agent.py --loop     # keep scanning every N hours
  python3 vpn_lead_agent.py --hours 12 # scan every 12h (default)
  python3 vpn_lead_agent.py --out leads.jsonl --limit 15

REQUIREMENTS: Python 3.8+, `requests`, VPN connected to a NON-blocked region.
"""
from __future__ import annotations
import argparse, json, re, sys, time, html as html_mod
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

UA = "Market-Intel-LeadAgent/1.0 (client-lead scanner)"
REDDIT_BASE = "https://www.reddit.com"
# Subreddits where people actively HIRE developers (the good stuff).
HIRE_SUBREDDITS = [
    "forhire", "freelance", "Entrepreneur", "startups", "smallbusiness",
    "SaaS", "webdev", "jobs", "ProgrammingBuddies", "needamod", "digitalnomad",
]

# Flair → client type. THE strongest signal.
def flair_type(flair: str) -> str | None:
    f = (flair or "").lower()
    if not f:
        return None
    if any(k in f for k in ("for hire", "forhire", "offering", "for sale", "freelancer")):
        return "not_a_client"   # freelancer advertising supply
    if any(k in f for k in ("hiring", "hire", "job", "client", "project")):
        return "hire"           # buyer, money on the table
    return None

# Title/body markers of a buyer vs an employee-listing vs a freelancer.
_BUY = [r"\blooking for (a )?(developer|dev|coder|freelancer)\b",
        r"\bneed (a )?(developer|dev|someone to build)\b",
        r"\bhire (a )?(developer|dev|freelancer)\b", r"\bbuild (a )?(website|app|mvp|saas)\b",
        r"\b(we|i) (need|want|require) (a )?(developer|dev)\b", r"\bbudget\b",
        r"\bpaying\b", r"\bproject (for|for sale)\b"]
_EMPLOYEE = [r"\b(manager|director|vp|head of|account executive|executive)\b",
             r"\b(full[- ]?time|permanent|salaried)\b", r"\b(closer|sales rep|vendor)\b"]
_AD = [r"\[for hire\]", r"\boffering\b", r"\btutoring\b", r"\bopen to (work|freelance)\b",
       r"\bi (am|am a) (freelance|developer)\b", r"\bavailable for\b"]

def classify(post: dict) -> tuple[str, int, str]:
    """Return (client_type, lead_score, reason)."""
    flair = flair_type(post.get("link_flair_text"))
    title = post.get("title", "")
    body = (post.get("selftext") or "")[:500]
    text = (title + " " + body).lower()
    reason = f"flair:{post.get('link_flair_text')}" if flair else "text_score"
    if flair == "not_a_client":
        return "not_a_client", 0, reason
    buyer = sum(1 for p in _BUY if re.search(p, text))
    emp = sum(1 for p in _EMPLOYEE if re.search(p, text))
    ad = sum(1 for p in _AD if re.search(p, text))
    if flair == "hire":
        buyer = max(buyer, 3)   # flair is explicit intent
    if ad >= 1:
        return "not_a_client", 0, "advertisement"
    if buyer == 0:
        return "not_a_client", 0, "no_buy_intent"
    score = min(100, 25 + buyer * 20 - emp * 8)
    if emp >= 1 or reason.startswith("flair"):
        # employee-job flair won't be 'hire' normally here
        pass
    if "for hire" not in reason:
        pass
    ttype = "freelance_client" if score >= 30 else "job_board_noise"
    return ttype, score, reason

def fetch_reddit(sub, limit=15) -> list[dict]:
    url = f"{REDDIT_BASE}/r/{sub}/new.json?" + urlencode({"limit": limit, "raw_json": 1})
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=20)
        if r.status_code != 200:
            print(f"  [{sub}] HTTP {r.status_code} — Reddit blocked this IP. "
                  f"Connect VPN to a residential region.")
            return []
        posts = r.json().get("data", {}).get("children", [])
        return [p["data"] for p in posts if p.get("kind") == "t3"]
    except Exception as e:
        print(f"  [{sub}] error: {e}")
        return []

def clean_html(s): return html_mod.unescape(re.sub(r"<[^>]+>", " ", s).strip())

def main():
    ap = argparse.ArgumentParser(description="VPN lead agent — Reddit freelance-hire leads")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--subs", default=",".join(HIRE_SUBREDDITS))
    ap.add_argument("--out", default="leads.jsonl")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--hours", type=float, default=12)
    args = ap.parse_args()
    subs = [s.strip() for s in args.subs.split(",") if s.strip()]

    while True:
        run(subs, args.limit, args.out)
        if not args.loop:
            break
        print(f"\n[+] Next scan in {args.hours}h. Ctrl-C to stop. (Keep VPN on.)")
        time.sleep(args.hours * 3600)

def run(subs, limit, out):
    print("=" * 60)
    print(f"Lead scan {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'Reddit check: '}if this hangs/403s, your VPN IP is blocked.")
    clients, all_posts = [], 0
    for sub in subs:
        posts = fetch_reddit(sub, limit)
        all_posts += len(posts)
        for p in posts:
            ctype, score, reason = classify(p)
            rec = {
                "subreddit": sub, "title": p.get("title"),
                "selftext": clean_html(p.get("selftext") or "")[:200],
                "url": "https://www.reddit.com" + (p.get("permalink") or ""),
                "author": p.get("author"), "flair": p.get("link_flair_text"),
                "score": p.get("score"), "num_comments": p.get("num_comments"),
                "client_type": ctype, "lead_score": score, "reason": reason,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }
            if ctype == "freelance_client":
                clients.append(rec)
        time.sleep(1)  # be gentle on Reddit
    # Save all
    with open(out, "a", encoding="utf-8") as f:
        for r in clients:
            f.write(json.dumps(r) + "\n")
    # Print ranked clients
    clients.sort(key=lambda c: -c["lead_score"])
    print(f"\n>>> {len(clients)} REAL CLIENT LEADS (from {all_posts} posts scanned)")
    for i, c in enumerate(clients[:20], 1):
        print(f"\n{i}. [{c['subreddit']}] score {c['lead_score']} — {c['title'][:70]}")
        print(f"   {c['url']}")
        print(f"   flair={c['flair']} | author u/{c['author']} | {c['num_comments']} comments")
    print(f"\n[+] Saved to {out}")

if __name__ == "__main__":
    main()
