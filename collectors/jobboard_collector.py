"""
Job boards collector — fetches dev/clients job postings.

Scrapes public job boards for roles that indicate a company OR individual
is actively hiring developer / freelance / contract work (a buying signal
for freelance developers and agencies).

Uses RemoteOK and workinstartups.com public APIs (free, no auth).
"""
from __future__ import annotations

import json
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from core.models import RawItem
from collectors.base import BaseCollector

USER_AGENT = "Market-Intel/1.0"

# Developer / freelance / contract keyword TOKENS (word-boundary matching).
# These match real job titles like "Custom Software Engineer", "Full Stack",
# "Node developer", "AI Integration", etc. — where literal substring "web
# developer" would miss 100% of hits.
DEV_KEYWORDS = [
    "developer", "engineer", "software", "full stack", "fullstack",
    "frontend", "front end", "backend", "back end", "react", "node",
    "python", "javascript", "typescript", "programmer", "coding",
    "saas", "api", "website", "automation", "app",
]

# These must appear in the TITLE or TAGS (not the noisy description)
# to count as a dev / freelance hiring signal.
TITLE_OR_TAGS_KEYWORDS = DEV_KEYWORDS

def _match_keywords(text: str, keywords: list[str]) -> bool:
    """Word-boundary substring match on lowercased text.

    Matches if ANY keyword appears as a whole word (or inside a token
    boundary) within the text.
    """
    tl = text.lower()
    for kw in keywords:
        if kw in tl:
            return True
    return False


class JobBoardCollector(BaseCollector):
    name = "job_boards"

    def __init__(self, config: dict, retry_config: dict | None = None):
        super().__init__(config, retry_config)
        self._keywords: list[str] = config.get("keywords", DEV_KEYWORDS)
        self._srcs: list[str] = config.get("sources", ["remoteok", "workinstartups"])

    def _fetch(self) -> list[RawItem]:
        all_items: list[RawItem] = []

        if "remoteok" in self._srcs:
            items = self._fetch_remoteok()
            all_items.extend(items)

        if "workinstartups" in self._srcs:
            items = self._fetch_workinstartups()
            all_items.extend(items)

        return all_items

    def _fetch_remoteok(self) -> list[RawItem]:
        """Fetch from RemoteOK public API."""
        url = "https://remoteok.com/api"
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self._logger.warning(f"RemoteOK fetch failed: {e}")
            return []

        # First element is metadata, rest are jobs
        jobs = data[1:] if isinstance(data, list) and len(data) > 1 else data.get("jobs", [])
        items: list[RawItem] = []

        for job in jobs:
            if not isinstance(job, dict):
                continue

            title = job.get("position") or job.get("title", "")
            company = job.get("company", "")
            job_url = job.get("url", "")
            description = job.get("description", "")[:500]
            tags = job.get("tags", [])

            # Dev signal comes from the TITLE only. RemoteOK tags are too
            # broad (catch unrelated jobs) and the description is too noisy —
            # both cause false positives. Title-only is the cleanest signal.
            title_lower = title.lower()
            if not _match_keywords(title_lower, self._keywords):
                continue

            if not title or not job_url:
                continue

            # Clean HTML from description
            clean_desc = re.sub(r"<[^>]+>", " ", description)
            clean_desc = re.sub(r"\s+", " ", clean_desc).strip()

            item = RawItem.create(
                source="job_boards",
                source_name=f"RemoteOK / {company}",
                title=f"{title} at {company}",
                url=job_url,
                body=clean_desc,
                author=company,
                published_at=str(job.get("epoch")) if job.get("epoch") else None,
                score=job.get("views", 0),
                tags=tags[:5] if isinstance(tags, list) else [],
                metadata={
                    "company": company,
                    "position": title,
                    "location": job.get("location", "Remote"),
                    "salary": job.get("salary", ""),
                    "board": "remoteok",
                },
            )
            items.append(item)

        self._logger.info(f"RemoteOK: {len(items)} dev jobs", extra={"items": len(items)})
        return items

    def _fetch_workinstartups(self) -> list[RawItem]:
        """Fetch from workinstartups.com RSS feed."""
        url = "https://workinstartups.com/jobs/marketing/feed/"

        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/xml, text/xml",
        })

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                xml_content = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            self._logger.warning(f"Workinstartups fetch failed: {e}")
            return []

        # Parse RSS using the module-level helper
        from collectors.rss_collector import RSSCollector
        root = RSSCollector._parse_rss_from_xml(xml_content)

        items: list[RawItem] = []
        if root is None:
            return items

        import xml.etree.ElementTree as ET
        channel = root.find("channel")
        if channel is None:
            return items

        for item_elem in channel.findall("item"):
            title = RSSCollector._get_text(item_elem, "title")
            link = RSSCollector._get_text(item_elem, "link")
            description = RSSCollector._get_text(item_elem, "description")
            pub_date = RSSCollector._get_text(item_elem, "pubDate")

            if not title or not link:
                continue

            body = RSSCollector._strip_html(description)[:500] if description else ""

            item = RawItem.create(
                source="job_boards",
                source_name="Workinstartups",
                title=title.strip(),
                url=link.strip(),
                body=body,
                published_at=RSSCollector._parse_date(pub_date),
                tags=["job_posting", "marketing"],
                metadata={"board": "workinstartups"},
            )
            items.append(item)

        self._logger.info(f"Workinstartups: {len(items)} jobs", extra={"items": len(items)})
        return items