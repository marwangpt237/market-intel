"""
Reddit collector — fetches top posts from configured subreddits.

Uses Reddit's public JSON API (no authentication required).
Each subreddit returns hot/new/top posts with title, URL, score, and selftext.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.parse
from typing import Any
from core.models import RawItem
from core.logger import get_logger
from collectors.base import BaseCollector


REDDIT_BASE = "https://www.reddit.com"
USER_AGENT = "Market-Intel/1.0 (Python; +https://github.com/marwangpt237/market-intel)"


class RedditCollector(BaseCollector):
    name = "reddit"

    def __init__(self, config: dict, retry_config: dict | None = None):
        super().__init__(config, retry_config)
        self._subreddits: list[str] = config.get("subreddits", [])
        self._sort: str = config.get("sort", "hot")
        self._time_range: str = config.get("time_range", "day")
        self._min_score: int = config.get("min_score", 0)

    def _fetch(self) -> list[RawItem]:
        all_items: list[RawItem] = []

        for subreddit in self._subreddits:
            self._logger.info(f"Fetching r/{subreddit}", extra={"subreddit": subreddit})
            try:
                items = self._fetch_subreddit(subreddit)
                all_items.extend(items)
            except Exception as e:
                self._logger.warning(
                    f"Failed to fetch r/{subreddit}",
                    extra={"subreddit": subreddit, "error": str(e)}
                )

        return all_items

    def _fetch_subreddit(self, subreddit: str) -> list[RawItem]:
        """Fetch posts from a single subreddit."""
        sort = self._sort
        params = {"limit": "25"}
        if sort == "top":
            params["t"] = self._time_range

        url = f"{REDDIT_BASE}/r/{subreddit}/{sort}.json?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        posts = data.get("data", {}).get("children", [])
        items: list[RawItem] = []

        for post_wrapper in posts:
            post = post_wrapper.get("data", {})
            score = post.get("score", 0)

            # Filter by minimum score
            if score < self._min_score:
                continue

            # Skip stickied posts
            if post.get("stickied"):
                continue

            title = post.get("title", "").strip()
            permalink = post.get("permalink", "")
            post_url = f"{REDDIT_BASE}{permalink}" if permalink else post.get("url", "")

            # Use selftext as body if available, otherwise leave empty
            body = (post.get("selftext") or "")[:500].strip()

            item = RawItem.create(
                source="reddit",
                source_name=f"r/{subreddit}",
                title=title,
                url=post_url,
                body=body,
                author=post.get("author", ""),
                published_at=self._timestamp_to_iso(post.get("created_utc")),
                score=score,
                tags=[subreddit],
                metadata={
                    "subreddit": subreddit,
                    "num_comments": post.get("num_comments", 0),
                    "upvote_ratio": post.get("upvote_ratio", 0),
                    "is_self": post.get("is_self", False),
                    "link_flair_text": post.get("link_flair_text"),
                },
            )
            items.append(item)

        self._logger.info(
            f"r/{subreddit}: {len(items)} items (min_score={self._min_score})",
            extra={"subreddit": subreddit, "items": len(items)}
        )
        return items

    @staticmethod
    def _timestamp_to_iso(ts: float | None) -> str | None:
        if ts is None:
            return None
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
