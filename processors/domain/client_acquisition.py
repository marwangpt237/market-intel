"""
Client Acquisition domain module — detects signals for freelance/agency
developer work.

Answers the question: "Who is actively looking to hire a developer
right now, where are they, what do they need, and what's the best way
to reach them?"

Signals extracted (stored in item.metadata["domain_signals"]["client_acq"]):

  buying_intent (HIGH — direct revenue signal):
    - looking_for_developer: "looking for developer", "need a dev"
    - hiring_freelance: "hiring freelance", "freelance developer"
    - need_website: "need a website", "build a website"
    - need_mvp: "need an mvp", "build an mvp"
    - need_app: "need an app", "build a mobile app"
    - need_saas: "build a saas", "saas product"
    - agency_recommendation: "agency recommendations", "recommend a developer"
    - technical_cofounder: "technical co-founder", "cto as a service"
    - build_project: "build a project", "need someone to build"

  budget_signals (HIGH — buying readiness):
    - has_budget: "budget for", "have $X", "willing to pay"
    - ready_to_start: "ready to start", "this week", "asap", "urgent"
    - funded: "funded", "raised", "seed", "series A"
    - ready_to_hire: "ready to hire", "looking to hire"

  niche (extracted as entity — what industry is the prospect in?):
    - saas, legal, medical, ecommerce, logistics, fintech, real_estate,
      education, crypto, agency, startup, enterprise

  country (extracted as entity — where is the prospect?):
    - UK, USA, Canada, Australia, Germany, France, Netherlands, UAE,
      Singapore, etc.
    - Also extracts cities: London, NYC, San Francisco, Berlin, etc.

  project_type (extracted as entity — what do they need built?):
    - website, mvp, mobile_app, saas, integration, api, dashboard,
      landing_page, ecommerce, migration, ai_integration

  outreach_channel (recommended based on source):
    - reddit_dm, reddit_reply, hn_email, hn_reply, linkedin_connect,
      linkedin_dm, job_board_apply, email, twitter_dm

  lead_score (0-100): composite of buying_intent + budget + niche match
"""
from __future__ import annotations
import re
from core.models import ProcessedItem
from processors.domain.base import BaseDomainModule


# ─── Buying intent patterns ─────────────────────────────────────────────
# Each pattern: (signal_name, regex, weight)
_BUYING_INTENT_PATTERNS: list[tuple[str, str, int]] = [
    # Direct hiring signals (HIGH)
    ("looking_for_developer", r"\b(looking for (a )?developer|need a developer|need a dev|seeking developer)\b", 5),
    ("hiring_freelance", r"\b(hiring freelance|freelance developer|freelance dev|contract developer|contractor)\b", 5),
    ("agency_recommendation", r"\b(agency recommendations|recommend a (developer|agency)|know any (good )?developer|any (good )?agencies)\b", 5),
    ("technical_cofounder", r"\b(technical co[- ]?founder|cto as a service|tech co[- ]?founder|technical partner)\b", 4),
    ("ready_to_hire", r"\b(ready to hire|looking to hire|hiring now|hiring immediately)\b", 4),

    # Project-type intent (HIGH)
    ("need_website", r"\b(need (a |a new )?website|build (a )?website|(my|our|a)? ?website redesign|website rebuild|website (re)?design)\b", 4),
    ("need_mvp", r"\b(need (an? )?mvp|build (an? )?mvp|mvp development|build (a )?prototype)\b", 5),
    ("need_app", r"\b(need (an? )?(mobile )?app|build (an? )?app|mobile app development|ios app|android app)\b", 4),
    ("need_saas", r"\b(build (a )?saas|saas (product|platform|app)|subscription (product|service))\b", 4),
    ("need_dashboard", r"\b(need (a )?dashboard|build (a )?dashboard|admin panel|analytics dashboard)\b", 3),
    ("need_landing", r"\b(need (a )?landing page|build (a )?landing page|landing page design)\b", 3),
    ("need_api", r"\b(need (an? )?api|build (an? )?api|api development|api integration)\b", 3),
    ("need_integration", r"\b(integration (help|needed)|stripe integration|payment integration|crm integration)\b", 3),
    ("need_ecommerce", r"\b(need (a )?store|ecommerce (site|store)|shopify (store|site)|woocommerce)\b", 4),
    ("need_migration", r"\b(migration (help|needed)|refactor|migrate (from|to)|legacy (code|system) (refactor|migration))\b", 3),
    ("need_ai_integration", r"\b(ai integration|gpt integration|llm integration|chatgpt integration|ai feature)\b", 4),
    ("build_project", r"\b(need someone to build|looking for someone to build|need a team to build)\b", 4),
]

# ─── Budget / readiness signals ─────────────────────────────────────────
_BUDGET_PATTERNS: list[tuple[str, str, int]] = [
    ("has_budget", r"\b(budget (of|is|for|,)|have \$\d+|willing to pay|my budget|allocated \$\d+|have budget|with budget|funding|paying \$\d+|pays? \$\d+|pay \d+|compensat)", 4),
    ("budget_amount", r"\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.?\d*)\s*k?\b", 3),
    ("ready_to_start", r"\b(ready to start|starting (now|this week|asap)|onboard (now|this week))\b", 3),
    ("urgent", r"\b(urgent|asap|immediately|right away|this week|by next week)\b", 2),
    ("funded", r"\b(funded|raised (seed|series [ab])|bootstrapped|pre[- ]?seed|angel backed|vc backed|seed round|series [ab])\b", 4),
    ("paying_customer", r"\b(paying customer|revenue|making money|have users|in production)\b", 3),
]

# ─── Niche detection ────────────────────────────────────────────────────
_NICHE_PATTERNS: dict[str, list[str]] = {
    "saas": ["saas", "subscription", "b2b software", "mrr", "arr", "monthly recurring"],
    "legal": ["law firm", "attorney", "lawyer", "legal practice", "law office", "solicitor"],
    "medical": ["clinic", "healthcare", "medical practice", "hospital", "doctor", "patient", "hipaa"],
    "ecommerce": ["ecommerce", "online store", "shopify", "woocommerce", "magento", "dropshipping"],
    "logistics": ["logistics", "shipping", "supply chain", "warehouse", "fulfillment", "freight"],
    "fintech": ["fintech", "payment", "banking", "neobank", "lending", "insurance tech"],
    "real_estate": ["real estate", "property", "realtor", "brokerage", "listings"],
    "education": ["education", "edtech", "course", "learning platform", "lms", "training"],
    "crypto": ["crypto", "web3", "blockchain", "defi", "nft", "smart contract", "solidity"],
    "agency": ["agency", "studio", "consultancy", "marketing agency"],
    "startup": ["startup", "founder", "co-founder", "early stage", "pre-seed", "y combinator"],
    "enterprise": ["enterprise", "fortune 500", "corporate", "large org"],
    "nonprofit": ["nonprofit", "ngo", "charity", "foundation"],
    "hospitality": ["restaurant", "hotel", "hospitality", "booking"],
    "manufacturing": ["manufacturing", "factory", "production line", "industrial"],
}

# ─── Country / location detection ───────────────────────────────────────
_COUNTRY_PATTERNS: dict[str, list[str]] = {
    "UK": ["uk", "united kingdom", "london", "manchester", "birmingham", "edinburgh", "glasgow", "bristol", "leeds", "liverpool", "brighton"],
    "USA": ["usa", "united states", "america", "us ", "new york", "nyc", "san francisco", "sf", "los angeles", "la", "chicago", "boston", "austin", "seattle", "miami", "denver", "atlanta", "portland", "washington dc", "silicon valley"],
    "Canada": ["canada", "canadian", "toronto", "vancouver", "montreal", "calgary", "ottawa", "edmonton"],
    "Australia": ["australia", "australian", "sydney", "melbourne", "brisbane", "perth", "adelaide"],
    "Germany": ["germany", "german", "berlin", "munich", "hamburg", "frankfurt", "cologne", "stuttgart"],
    "France": ["france", "french", "paris", "lyon", "marseille", "bordeaux", "toulouse", "lille", "nantes"],
    "Netherlands": ["netherlands", "dutch", "amsterdam", "rotterdam", "the hague", "utrecht", "eindhoven"],
    "UAE": ["uae", "dubai", "abu dhabi", "emirates", "united arab emirates"],
    "Singapore": ["singapore", "singaporean"],
    "Switzerland": ["switzerland", "swiss", "zurich", "geneva", "basel", "bern", "lausanne"],
    "Spain": ["spain", "spanish", "madrid", "barcelona", "valencia", "seville"],
    "Italy": ["italy", "italian", "rome", "milan", "turin", "naples", "florence"],
    "Ireland": ["ireland", "irish", "dublin", "cork", "galway"],
    "Sweden": ["sweden", "swedish", "stockholm", "gothenburg", "malmo"],
    "Norway": ["norway", "norwegian", "oslo", "bergen"],
    "Denmark": ["denmark", "danish", "copenhagen", "aarhus"],
    "Finland": ["finland", "finnish", "helsinki", "tampere"],
    "Poland": ["poland", "polish", "warsaw", "krakow", "wroclaw"],
    "Portugal": ["portugal", "portuguese", "lisbon", "porto"],
    "Brazil": ["brazil", "brazilian", "sao paulo", "rio de janeiro"],
    "Mexico": ["mexico", "mexican", "mexico city", "guadalajara", "monterrey"],
    "India": ["india", "indian", "mumbai", "delhi", "bangalore", "hyderabad", "chennai", "pune"],
    "Japan": ["japan", "japanese", "tokyo", "osaka", "kyoto"],
    "SouthKorea": ["south korea", "korean", "seoul", "busan"],
    "SaudiArabia": ["saudi arabia", "saudi", "riyadh", "jeddah"],
    "Qatar": ["qatar", "doha"],
    "Bahrain": ["bahrain", "manama"],
    "Kuwait": ["kuwait", "kuwait city"],
    "Oman": ["oman", "muscat"],
    "Egypt": ["egypt", "egyptian", "cairo", "alexandria"],
    "SouthAfrica": ["south africa", "cape town", "johannesburg", "durban"],
    "Nigeria": ["nigeria", "nigerian", "lagos", "abuja"],
    "Kenya": ["kenya", "nairobi"],
}

# ─── Project type detection ─────────────────────────────────────────────
_PROJECT_TYPE_PATTERNS: dict[str, list[str]] = {
    "website": ["website", "web site", "web build", "site redesign"],
    "mvp": ["mvp", "prototype", "proof of concept", "poc"],
    "mobile_app": ["mobile app", "ios app", "android app", "react native", "flutter"],
    "saas": ["saas", "subscription platform", "multi-tenant"],
    "dashboard": ["dashboard", "admin panel", "analytics dashboard", "reporting tool"],
    "landing_page": ["landing page", "marketing site", "one-page site"],
    "api": ["api", "rest api", "graphql", "backend api"],
    "integration": ["integration", "stripe integration", "payment integration", "crm integration", "third-party"],
    "ecommerce": ["ecommerce", "online store", "shopify store", "woocommerce", "magento"],
    "migration": ["migration", "refactor", "legacy modernization", "replatform"],
    "ai_integration": ["ai integration", "gpt integration", "llm", "chatgpt", "ai feature", "ai assistant", "rag"],
    "automation": ["automation", "workflow automation", "zapier", "n8n"],
    "devops": ["devops", "ci/cd", "kubernetes", "infrastructure", "aws setup"],
}

# ─── Outreach channel mapping ───────────────────────────────────────────
_OUTREACH_CHANNEL_BY_SOURCE: dict[str, str] = {
    "reddit": "reddit_reply",
    "hacker_news": "hn_reply",
    "github_issues": "github_comment",
    "linkedin": "linkedin_connect",
    "rss": "email_or_linkedin",
    "google_news": "email_or_linkedin",
    "product_hunt": "ph_comment_or_linkedin",
    "g2": "email_or_linkedin",
    "job_boards": "job_board_apply",
    "workinstartups": "job_board_apply",
    "remoteok": "job_board_apply",
}


class ClientAcquisitionModule(BaseDomainModule):
    """Detects client acquisition signals in items.

    Extracts: buying_intent signals, budget signals, niche, country,
    project_type, recommended outreach channel, and a composite lead_score.
    """
    domain_name = "client_acquisition"

    def extract(self, item: ProcessedItem) -> dict:
        title = item.title or ""
        body = item.body or ""
        text = f"{title} {body}"
        text_lower = text.lower()

        if not text.strip():
            return {"signals": [], "severity": "none", "entities": {}}

        # ─── Buying intent ──────────────────────────────────────────────
        buying_signals: list[str] = []
        buying_score = 0
        for signal_name, pattern, weight in _BUYING_INTENT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                buying_signals.append(signal_name)
                buying_score += weight

        # ─── Budget signals ─────────────────────────────────────────────
        budget_signals: list[str] = []
        budget_score = 0
        budget_amounts: list[float] = []

        for signal_name, pattern, weight in _BUDGET_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                budget_signals.append(signal_name)
                budget_score += weight
                # Capture budget amounts
                if signal_name == "budget_amount":
                    for m in matches:
                        try:
                            # Handle "10" or "10,000" or "10.5"
                            cleaned = str(m).replace(",", "")
                            budget_amounts.append(float(cleaned))
                        except (ValueError, TypeError):
                            pass

        # ─── Niche detection ────────────────────────────────────────────
        niches: list[str] = []
        for niche, keywords in _NICHE_PATTERNS.items():
            for kw in keywords:
                if kw in text_lower:
                    niches.append(niche)
                    break  # one match per niche is enough

        # ─── Country detection ──────────────────────────────────────────
        countries: list[str] = []
        for country, keywords in _COUNTRY_PATTERNS.items():
            for kw in keywords:
                # Use word boundary for short keywords to avoid false matches
                if len(kw) <= 3:
                    if re.search(rf"\b{re.escape(kw)}\b", text_lower):
                        countries.append(country)
                        break
                elif kw in text_lower:
                    countries.append(country)
                    break

        # ─── Project type detection ─────────────────────────────────────
        project_types: list[str] = []
        for ptype, keywords in _PROJECT_TYPE_PATTERNS.items():
            for kw in keywords:
                if kw in text_lower:
                    project_types.append(ptype)
                    break

        # ─── Outreach channel recommendation ────────────────────────────
        source = (item.source or "").lower()
        source_name = (item.source_name or "").lower()
        outreach_channel = _OUTREACH_CHANNEL_BY_SOURCE.get(source, "email_or_linkedin")
        # Override based on source_name patterns
        if "reddit" in source_name:
            outreach_channel = "reddit_reply"
        elif "hacker news" in source_name or "hn" in source_name:
            outreach_channel = "hn_reply"
        elif "linkedin" in source_name:
            outreach_channel = "linkedin_connect"
        elif "product hunt" in source_name:
            outreach_channel = "ph_comment_or_linkedin"
        elif "remoteok" in source_name or "workinstartups" in source_name:
            outreach_channel = "job_board_apply"

        # ─── Composite lead score (0-100) ───────────────────────────────
        # buying_score max ~ 30 (5 signals * 5 weight + 5 signals * 4 weight etc.)
        # budget_score max ~ 20
        # Niches + countries + project_types add small bonuses
        lead_score = min(100, int(
            buying_score * 2.5           # 0-50 range
            + budget_score * 2.0          # 0-30 range
            + (10 if niches else 0)       # niche known = +10
            + (10 if countries else 0)    # location known = +10
            + (5 if project_types else 0) # project type known = +5
        ))

        # ─── Severity ───────────────────────────────────────────────────
        if lead_score >= 40:
            severity = "high"
        elif lead_score >= 20:
            severity = "medium"
        elif lead_score >= 5:
            severity = "low"
        else:
            severity = "none"

        # ─── Compile signals ────────────────────────────────────────────
        all_signals = buying_signals + budget_signals

        # ─── Entities ───────────────────────────────────────────────────
        entities: dict = {
            "niches": niches,
            "countries": countries,
            "project_types": project_types,
            "outreach_channel": outreach_channel,
            "lead_score": lead_score,
            "buying_intent_score": buying_score,
            "budget_score": budget_score,
        }
        if budget_amounts:
            entities["budget_amounts"] = budget_amounts

        return {
            "signals": all_signals,
            "severity": severity,
            "severity_score": lead_score,
            "entities": entities,
        }
