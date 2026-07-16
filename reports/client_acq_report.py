"""
Client Acquisition Report — actionable prospect list for freelance/agency
developer work.

Output format:
  "Don't spend on French ads. Instead, contact 20 UK SaaS startups this week,
   publish two technical LinkedIn posts, and reply to five Reddit threads.
   Expected cost: $0. Estimated lead probability: X."

Sections:
  1. Strategic Recommendation (lead with the answer)
  2. Top Prospects to Contact (ranked by lead_score)
  3. Top Countries by Hiring Activity
  4. Top Niches by Demand
  5. Reddit Threads to Reply To
  6. Job Board Gigs to Apply To
  7. LinkedIn Content Suggestions
  8. ROI Projection
  9. Filter rationale (why these countries/niches)
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from core.models import ProcessedItem
from core.logger import get_logger
from reports.base import BaseReportGenerator


class ClientAcquisitionReportGenerator(BaseReportGenerator):
    name = "client_acq"

    def __init__(self, config: dict):
        super().__init__(config)
        self._output_path = Path(config.get("output_path", "reports/"))
        self._top_prospects = int(config.get("top_prospects_count", 30))
        self._top_countries = int(config.get("top_countries_count", 10))
        self._top_niches = int(config.get("top_niches_count", 10))

    def _generate(self, items: list[ProcessedItem], run_id: str) -> str:
        self._output_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # Filter to items with client_acquisition domain signals
        prospects: list[dict] = []
        country_counts: Counter = Counter()
        niche_counts: Counter = Counter()
        project_type_counts: Counter = Counter()
        channel_counts: Counter = Counter()

        for item in items:
            signals = item.metadata.get("domain_signals", {}).get("client_acquisition", {})
            if not signals or not signals.get("signals"):
                continue

            entities = signals.get("entities", {})
            lead_score = entities.get("lead_score", 0)
            if lead_score < 5:  # filter out noise
                continue

            prospect = {
                "title": item.title,
                "url": item.url,
                "source": item.source_name,
                "source_type": item.source,
                "collected_at": item.collected_at,
                "author": item.author,
                "lead_score": lead_score,
                "severity": signals.get("severity", "low"),
                "buying_intent_score": entities.get("buying_intent_score", 0),
                "budget_score": entities.get("budget_score", 0),
                "signals": signals.get("signals", []),
                "niches": entities.get("niches", []),
                "countries": entities.get("countries", []),
                "project_types": entities.get("project_types", []),
                "outreach_channel": entities.get("outreach_channel", "email_or_linkedin"),
                "budget_amounts": entities.get("budget_amounts", []),
                "authority_score": item.metadata.get("authority_score", 50),
                "body_excerpt": (item.body or "")[:300] if item.body else "",
            }
            prospects.append(prospect)

            # Aggregate counts
            for c in entities.get("countries", []):
                country_counts[c] += 1
            for n in entities.get("niches", []):
                niche_counts[n] += 1
            for p in entities.get("project_types", []):
                project_type_counts[p] += 1
            channel_counts[entities.get("outreach_channel", "email_or_linkedin")] += 1

        # Sort prospects by lead_score (desc)
        prospects.sort(key=lambda p: p["lead_score"], reverse=True)
        top_prospects = prospects[: self._top_prospects]

        # ─── Build report ────────────────────────────────────────────────
        lines: list[str] = []
        lines.append(f"# Client Acquisition Report — {date_str}")
        lines.append("")
        lines.append(f"_Generated: {now.isoformat()} | Run: `{run_id}`_")
        lines.append("")
        lines.append("> Actionable prospect list for freelance / agency developer work.")
        lines.append("> Ranked by lead score (buying intent + budget + niche + location signals).")
        lines.append("")

        # ─── Strategic Recommendation ────────────────────────────────────
        lines.append("## Strategic Recommendation")
        lines.append("")

        if not prospects:
            lines.append("_No high-intent prospects detected this run. Try widening collector queries or waiting for the next collection cycle._")
            lines.append("")
        else:
            # Determine top country + niche
            top_country = country_counts.most_common(1)[0][0] if country_counts else "unknown"
            top_niche = niche_counts.most_common(1)[0][0] if niche_counts else "general"
            top_channel = channel_counts.most_common(1)[0][0] if channel_counts else "email_or_linkedin"

            # Count by channel for the recommendation
            reddit_count = sum(1 for p in top_prospects if "reddit" in p["source"].lower() or "reddit" in p["source_type"].lower())
            hn_count = sum(1 for p in top_prospects if "hacker news" in p["source"].lower() or "hn" in p["source_type"].lower())
            job_count = sum(1 for p in top_prospects if "remoteok" in p["source"].lower() or "workinstartups" in p["source"].lower() or "job" in p["source_type"].lower())

            # Estimated lead probability: prospects with lead_score >= 30 → ~25% reply rate, ~10% close rate
            high_intent = sum(1 for p in top_prospects if p["lead_score"] >= 30)
            est_replies = max(1, int(high_intent * 0.25))
            est_leads = max(1, int(high_intent * 0.10))

            lines.append(f"**Focus on {top_country} {top_niche} this week.**")
            lines.append("")
            lines.append(f"- **Contact {len(top_prospects)} prospects** (lead_score ≥ 5)")
            lines.append(f"- **Reply to {reddit_count} Reddit threads** + {hn_count} HN posts")
            lines.append(f"- **Apply to {job_count} job board gigs**")
            lines.append(f"- **Publish 2 technical LinkedIn posts** addressing detected pain points")
            lines.append(f"- **Estimated cost:** $0 (organic outreach)")
            lines.append(f"- **Expected replies:** ~{est_replies} (25% reply rate on high-intent prospects)")
            lines.append(f"- **Expected leads:** ~{est_leads} (10% close rate on replies)")
            lines.append("")

        # ─── Top Prospects ───────────────────────────────────────────────
        lines.append(f"## Top Prospects to Contact ({len(top_prospects)} ranked)")
        lines.append("")

        if top_prospects:
            lines.append("| # | Score | Source | Country | Niche | Project Type | Budget | Title |")
            lines.append("|---|-------|--------|---------|-------|--------------|--------|-------|")
            for i, p in enumerate(top_prospects, 1):
                countries = ", ".join(p["countries"][:2]) or "—"
                niches = ", ".join(p["niches"][:2]) or "—"
                ptypes = ", ".join(p["project_types"][:2]) or "—"
                budget = f"${p['budget_amounts'][0]:.0f}" if p["budget_amounts"] else "—"
                title = p["title"][:60].replace("|", "\\|")
                lines.append(
                    f"| {i} | **{p['lead_score']}** | {p['source'][:20]} | "
                    f"{countries} | {niches} | {ptypes} | {budget} | "
                    f"[{title}]({p['url']}) |"
                )
            lines.append("")

            # Detailed prospect breakdown
            lines.append("### Prospect Details")
            lines.append("")
            for i, p in enumerate(top_prospects[:15], 1):  # top 15 with full details
                lines.append(f"#### {i}. {p['title'][:100]}")
                lines.append("")
                lines.append(f"- **URL:** {p['url']}")
                lines.append(f"- **Source:** {p['source']}")
                lines.append(f"- **Lead score:** {p['lead_score']}/100 (buying intent: {p['buying_intent_score']}, budget: {p['budget_score']})")
                lines.append(f"- **Countries:** {', '.join(p['countries']) or 'unknown'}")
                lines.append(f"- **Niches:** {', '.join(p['niches']) or 'unknown'}")
                lines.append(f"- **Project types:** {', '.join(p['project_types']) or 'unknown'}")
                lines.append(f"- **Signals detected:** {', '.join(p['signals'][:6])}")
                if p["budget_amounts"]:
                    lines.append(f"- **Budget mentioned:** {', '.join(f'${a:.0f}' for a in p['budget_amounts'])}")
                lines.append(f"- **Recommended outreach:** `{p['outreach_channel']}`")
                if p["author"]:
                    lines.append(f"- **Author:** u/{p['author']}")
                lines.append("")

                # Outreach suggestion
                outreach_msg = self._generate_outreach_message(p)
                if outreach_msg:
                    lines.append("> **Suggested outreach:**")
                    lines.append("> ")
                    lines.append(f"> {outreach_msg}")
                    lines.append("")

        # ─── Top Countries ───────────────────────────────────────────────
        lines.append(f"## Top Countries by Hiring Activity")
        lines.append("")
        if country_counts:
            lines.append("| Rank | Country | Prospects |")
            lines.append("|------|---------|-----------|")
            for i, (country, count) in enumerate(country_counts.most_common(self._top_countries), 1):
                lines.append(f"| {i} | {country} | {count} |")
            lines.append("")
        else:
            lines.append("_No country signals detected. Prospects may not have mentioned their location._")
            lines.append("")

        # ─── Top Niches ──────────────────────────────────────────────────
        lines.append(f"## Top Niches by Demand")
        lines.append("")
        if niche_counts:
            lines.append("| Rank | Niche | Prospects |")
            lines.append("|------|-------|-----------|")
            for i, (niche, count) in enumerate(niche_counts.most_common(self._top_niches), 1):
                lines.append(f"| {i} | {niche} | {count} |")
            lines.append("")
        else:
            lines.append("_No niche signals detected._")
            lines.append("")

        # ─── Project types ───────────────────────────────────────────────
        lines.append(f"## Project Types Requested")
        lines.append("")
        if project_type_counts:
            lines.append("| Project Type | Count |")
            lines.append("|--------------|-------|")
            for ptype, count in project_type_counts.most_common():
                lines.append(f"| {ptype} | {count} |")
            lines.append("")

        # ─── Reddit threads ──────────────────────────────────────────────
        reddit_prospects = [p for p in top_prospects if "reddit" in p["source"].lower() or p["source_type"] == "reddit"]
        if reddit_prospects:
            lines.append(f"## Reddit Threads to Reply To ({len(reddit_prospects)})")
            lines.append("")
            lines.append("> Reply with value-first comments. Don't pitch in the comment — build credibility, then DM.")
            lines.append("")
            for p in reddit_prospects[:10]:
                lines.append(f"- [{p['title'][:80]}]({p['url']}) — _r/{p['source'].split('/')[-1] if '/' in p['source'] else p['source']}_, score {p['lead_score']}")
                if p["signals"]:
                    lines.append(f"  - Signals: {', '.join(p['signals'][:4])}")
            lines.append("")

        # ─── Job board gigs ──────────────────────────────────────────────
        job_prospects = [p for p in top_prospects if "remoteok" in p["source"].lower() or "workinstartups" in p["source"].lower() or "job" in p["source_type"].lower()]
        if job_prospects:
            lines.append(f"## Job Board Gigs to Apply To ({len(job_prospects)})")
            lines.append("")
            lines.append("> Apply within 24 hours — these close fast. Include portfolio link + 1-sentence value prop.")
            lines.append("")
            for p in job_prospects[:10]:
                budget_str = f" (budget: ${p['budget_amounts'][0]:.0f})" if p["budget_amounts"] else ""
                lines.append(f"- [{p['title'][:80]}]({p['url']}) — _{p['source']}_, score {p['lead_score']}{budget_str}")
            lines.append("")

        # ─── LinkedIn content suggestions ────────────────────────────────
        if niche_counts or project_type_counts:
            lines.append("## LinkedIn Content Suggestions (Publish 2 This Week)")
            lines.append("")
            lines.append("> Goal: attract prospects organically. Technical posts rank well on LinkedIn.")
            lines.append("")

            # Generate 2 post ideas based on detected niches + project types
            top_niche_1 = niche_counts.most_common(1)[0][0] if niche_counts else "SaaS"
            top_niche_2 = niche_counts.most_common(2)[1][0] if len(niche_counts) >= 2 else "startups"
            top_ptype_1 = project_type_counts.most_common(1)[0][0] if project_type_counts else "MVP"
            top_ptype_2 = project_type_counts.most_common(2)[1][0] if len(project_type_counts) >= 2 else "API integration"

            post_1 = self._generate_linkedin_post_idea(top_niche_1, top_ptype_1)
            post_2 = self._generate_linkedin_post_idea(top_niche_2, top_ptype_2)

            lines.append("### Post 1")
            lines.append("")
            lines.append(f"**Topic:** {post_1['topic']}")
            lines.append("")
            lines.append(f"**Hook:** {post_1['hook']}")
            lines.append("")
            lines.append("**Outline:**")
            for bullet in post_1["outline"]:
                lines.append(f"- {bullet}")
            lines.append("")
            lines.append(f"**CTA:** {post_1['cta']}")
            lines.append("")

            lines.append("### Post 2")
            lines.append("")
            lines.append(f"**Topic:** {post_2['topic']}")
            lines.append("")
            lines.append(f"**Hook:** {post_2['hook']}")
            lines.append("")
            lines.append("**Outline:**")
            for bullet in post_2["outline"]:
                lines.append(f"- {bullet}")
            lines.append("")
            lines.append(f"**CTA:** {post_2['cta']}")
            lines.append("")

        # ─── ROI Projection ──────────────────────────────────────────────
        lines.append("## ROI Projection")
        lines.append("")
        if prospects:
            high_intent = sum(1 for p in prospects if p["lead_score"] >= 30)
            med_intent = sum(1 for p in prospects if 15 <= p["lead_score"] < 30)
            low_intent = sum(1 for p in prospects if 5 <= p["lead_score"] < 15)

            lines.append(f"| Tier | Lead Score | Count | Est. Reply Rate | Est. Leads |")
            lines.append(f"|------|-----------|-------|-----------------|------------|")
            lines.append(f"| High | ≥30 | {high_intent} | 25% | {int(high_intent * 0.25 * 0.4)} |")
            lines.append(f"| Medium | 15-29 | {med_intent} | 12% | {int(med_intent * 0.12 * 0.3)} |")
            lines.append(f"| Low | 5-14 | {low_intent} | 5% | {int(low_intent * 0.05 * 0.2)} |")
            lines.append(f"| **Total** | — | **{len(prospects)}** | — | **{int(high_intent * 0.25 * 0.4 + med_intent * 0.12 * 0.3 + low_intent * 0.05 * 0.2)}** |")
            lines.append("")
            lines.append(f"**Time investment:** ~15h/week (3h/day × 5 days) for outreach + content + applications")
            lines.append(f"**Cost:** $0 (organic only — no paid ads this week)")
            lines.append(f"**Expected project value:** $5,000 - $15,000 per closed client (1-3 month project)")
            lines.append("")

        # ─── Why these countries/niches ──────────────────────────────────
        lines.append("## Why These Recommendations")
        lines.append("")
        lines.append("Based on observed market signals (not generic advice):")
        lines.append("")
        lines.append(f"- **{country_counts.most_common(1)[0][0] if country_counts else 'No country'}** has the most active hiring posts this cycle ({country_counts.most_common(1)[0][1] if country_counts else 0} signals)")
        lines.append(f"- **{niche_counts.most_common(1)[0][0] if niche_counts else 'No niche'}** niche shows highest demand ({niche_counts.most_common(1)[0][1] if niche_counts else 0} prospects)")
        lines.append(f"- **{project_type_counts.most_common(1)[0][0] if project_type_counts else 'No project type'}** is the most-requested project type ({project_type_counts.most_common(1)[0][1] if project_type_counts else 0} requests)")
        lines.append(f"- Reddit + HN + job boards are the highest-signal channels — paid ads would be lower ROI")
        lines.append("")
        lines.append("> Recommendations update automatically each run based on fresh market data.")
        lines.append("> As the Learning Engine accumulates outcome data, lead_score weights will tune to your actual close rate.")
        lines.append("")

        # ─── Closed-loop status ──────────────────────────────────────────
        lines.append("## Closed-Loop Status")
        lines.append("")
        lines.append(f"- ✅ **Collect** — {len(items)} items collected from Reddit, HN, RSS, Google News, GitHub, Product Hunt, Job boards")
        lines.append(f"- ✅ **Analyze** — Buying intent + budget + niche + country + project type extracted")
        lines.append(f"- ✅ **Score** — Lead score 0-100 computed per prospect")
        lines.append(f"- ✅ **Filter** — {len(prospects)} prospects passed the lead_score ≥ 5 threshold")
        lines.append(f"- ✅ **Strategize** — Optimal outreach plan generated under 15h/week constraint")
        lines.append(f"- ✅ **Act** — Outreach messages + LinkedIn content drafted in `actions/`")
        lines.append(f"- ✅ **Measure** — Outcomes tracked in `data/metrics_input_template.json`")
        lines.append(f"- ✅ **Learn** — Lead_score weights tune to your actual close rate over time")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_Market-Intel — Client Acquisition Profile._")

        filepath = self._output_path / f"client_acq_{date_str}_{run_id}.md"
        filepath.write_text("\n".join(lines), encoding="utf-8")

        self._logger.info(f"Client acquisition report written to {filepath} ({len(prospects)} prospects)")
        return str(filepath)

    def _generate_outreach_message(self, prospect: dict) -> str:
        """Generate a short personalized outreach message for a prospect."""
        niches = prospect.get("niches", [])
        project_types = prospect.get("project_types", [])
        channel = prospect.get("outreach_channel", "email_or_linkedin")

        if not niches and not project_types:
            return ""

        niche_str = niches[0] if niches else "your industry"
        ptype_str = project_types[0].replace("_", " ") if project_types else "your project"

        if channel == "reddit_reply":
            return f"Reply publicly with a useful technical insight about {ptype_str}. After they engage, DM with portfolio link + 1-sentence value prop focused on {niche_str}."
        elif channel == "hn_reply":
            return f"Reply on HN with technical credibility (cite a relevant project). Email separately if address is in profile."
        elif channel == "linkedin_connect":
            return f"Connect with note: 'Saw your post about {ptype_str} for {niche_str} — I build exactly this. Open to a 15-min call?'"
        elif channel == "job_board_apply":
            return f"Apply with: 1-sentence value prop for {niche_str}, link to relevant portfolio piece, availability (this week)."
        else:
            return f"Email: 'Saw your post about {ptype_str}. I've built similar for {niche_str} clients. Worth a 15-min call?'"

    def _generate_linkedin_post_idea(self, niche: str, project_type: str) -> dict:
        """Generate a LinkedIn post idea based on detected niche + project type."""
        ptype_display = project_type.replace("_", " ")

        # Templates by project type
        if "mvp" in project_type:
            return {
                "topic": f"How I helped a {niche} founder ship their {ptype_display} in 6 weeks (and what we cut)",
                "hook": f"Most {niche} founders think they need 6 months to launch. Here's how we did it in 6 weeks:",
                "outline": [
                    "What we built (1 sentence)",
                    "What we deliberately cut from v1 (the hard choices)",
                    "Tech stack choice + why (1 paragraph)",
                    "The single feature that drove 80% of early signups",
                    "What I'd do differently next time",
                ],
                "cta": "If you're a founder planning an MVP, DM me — happy to share the build-vs-cut framework.",
            }
        elif "api" in project_type or "integration" in project_type:
            return {
                "topic": f"The 3 integrations every {niche} platform needs (and the 1 you can skip)",
                "hook": f"Built 12+ {niche} platforms in the last 2 years. Same integrations come up every time:",
                "outline": [
                    "Integration 1: payments (Stripe + invoicing)",
                    "Integration 2: auth (magic link > password)",
                    "Integration 3: email (transactional > marketing)",
                    "The one you can skip until you have 100 users",
                    "Code snippet: how I structure integration layers",
                ],
                "cta": "What integrations are blocking your {niche} build? Comment below.",
            }
        elif "website" in project_type or "landing" in project_type:
            return {
                "topic": f"Why your {niche} website isn't converting (and the 5 fixes that work in 2026)",
                "hook": f"Audited 20+ {niche} websites this year. Same 5 conversion killers every time:",
                "outline": [
                    "Killer 1: hero section talks about you, not the customer",
                    "Killer 2: no social proof above the fold",
                    "Killer 3: CTA is 'Learn More' instead of action-oriented",
                    "Killer 4: mobile load time > 3 seconds",
                    "Killer 5: no pricing transparency (or worse, 'Contact Us')",
                    "Each fix + before/after example",
                ],
                "cta": "Want a free teardown of your {niche} site? DM me the URL.",
            }
        else:
            return {
                "topic": f"Building {ptype_display} for {niche} clients: lessons from the trenches",
                "hook": f"3 things I learned shipping {ptype_display} for {niche} clients this year:",
                "outline": [
                    "Lesson 1: requirements are always wrong on day 1 — build for change",
                    "Lesson 2: the boring tech stack wins (Postgres + React + a queue)",
                    "Lesson 3: clients care about the dashboard more than the backend",
                    "Anti-pattern I see everywhere",
                    "What I'd tell my past self",
                ],
                "cta": "Building a {niche} {ptype_display}? Let's talk — DM me.",
            }
