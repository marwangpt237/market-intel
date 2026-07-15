"""
Job boards collector — fetches marketing/tech job postings.

Scrapes public job boards for marketing-related roles that mention
specific tools (indicates company tool adoption):
- "Looking for someone who knows HubSpot" → HubSpot user
- "Experience with SEMrush required" → SEMrush user

Uses RemoteOK and workinstartups.com public APIs (free, no auth).
"""
from __future__ import annotations

import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from core.models import RawItem
from collectors.base import BaseCollector


USER_AGENT = "Market-Intel/1.0"


class JobBoardCollector(BaseCollector):
    name = "job_boards"

    def __init__(self, config: dict, retry_config: dict | None = None):
        super().__init__(config, retry_config)
        self._keywords: list[str] = config.get("keywords", [
            "marketing", "growth", "SEO", "content marketing",
            "marketing automation", "paid ads", "social media marketing",
        ])
        self._sources: list[str] = config.get("sources", ["remoteok", "workinstartups"])

    def _fetch(self) -> list[RawItem]:
        all_items: list[RawItem] = []

        if "remoteok" in self._sources:
            items = self._fetch_remoteok()
            all_items.extend(items)

        if "workinstartups" in self._sources:
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

            # Filter: only marketing-related jobs
            text_lower = f"{title} {description} {' '.join(tags)}".lower()
            if not any(kw.lower() in text_lower for kw in self._keywords):
                continue

            if not title or not job_url:
                continue

            # Clean HTML from description
            import re
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

        self._logger.info(f"RemoteOK: {len(items)} marketing jobs", extra={"items": len(items)})
        return items

    def _fetch_workinstartups(self) -> list[RawItem]:
        """Fetch from workinstartups.com RSS feed."""
        # They have an RSS feed for marketing jobs
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

        # Parse RSS using the RSS collector's parser
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


# Helper function for RSS parsing (used by workinstartups)
def _parse_rss_from_xml(xml_content: str):
    import xml.etree.ElementTree as ET
    try:
        return ET.fromstring(xml_content)
    except ET.ParseError:
        return None
