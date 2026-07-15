"""
GitHub Issues collector — fetches trending issues with bounty/help-wanted labels.

Uses GitHub Issues Search API (no auth for public repos, rate-limited to
10 req/min). Searches for feature requests, bug reports, and discussions
related to marketing tools and competitors.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.parse
import os
from datetime import datetime, timezone
from core.models import RawItem
from collectors.base import BaseCollector


GITHUB_API = "https://api.github.com/search/issues"
USER_AGENT = "Market-Intel/1.0"


class GitHubIssuesCollector(BaseCollector):
    name = "github_issues"

    def __init__(self, config: dict, retry_config: dict | None = None):
        super().__init__(config, retry_config)
        self._queries: list[str] = config.get("queries", [
            "marketing automation tool",
            "SEO tool feature request",
            "email marketing alternative",
            "analytics dashboard open source",
        ])
        self._labels: list[str] = config.get("labels", ["help wanted", "enhancement", "feature"])
        self._token: str = os.environ.get("GITHUB_TOKEN", "") or config.get("github_token", "")

    def _fetch(self) -> list[RawItem]:
        all_items: list[RawItem] = []

        for query in self._queries:
            self._logger.info(f"Searching GitHub Issues: {query}", extra={"query": query})
            try:
                items = self._fetch_query(query)
                all_items.extend(items)
            except Exception as e:
                self._logger.warning(f"GitHub query failed: {query}", extra={"error": str(e)})

        return all_items

    def _fetch_query(self, query: str) -> list[RawItem]:
        # Build search query
        label_filter = " ".join(f'label:"{l}"' for l in self._labels)
        search_q = f"{query} {label_filter} is:issue is:open sort:created-desc"

        params = {"q": search_q, "per_page": 20, "sort": "created", "order": "desc"}
        url = f"{GITHUB_API}?{urllib.parse.urlencode(params)}"

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        }
        if self._token:
            headers["Authorization"] = f"token {self._token}"

        req = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        items_data = data.get("items", [])
        items: list[RawItem] = []

        for issue in items_data:
            title = issue.get("title", "").strip()
            html_url = issue.get("html_url", "")
            body = (issue.get("body") or "")[:500]
            created_at = issue.get("created_at")
            score = issue.get("comments", 0)
            labels = [l.get("name", "") for l in issue.get("labels", [])]

            repo_url = issue.get("repository_url", "")
            repo_name = repo_url.replace("https://api.github.com/repos/", "")

            if not title or not html_url:
                continue

            item = RawItem.create(
                source="github_issues",
                source_name=f"github/{repo_name}",
                title=title,
                url=html_url,
                body=body,
                author=issue.get("user", {}).get("login", ""),
                published_at=created_at,
                score=score,  # using comment count as engagement score
                tags=labels[:5],
                metadata={
                    "repo": repo_name,
                    "issue_number": issue.get("number"),
                    "state": issue.get("state"),
                    "labels": labels,
                    "comments": issue.get("comments", 0),
                },
            )
            items.append(item)

        self._logger.info(f"GitHub '{query}': {len(items)} issues", extra={"query": query, "items": len(items)})
        return items
