"""Daily Markdown intelligence report generator."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from collections import Counter, defaultdict
from core.models import ProcessedItem
from core.logger import get_logger
from reports.base import BaseReportGenerator


class MarkdownReportGenerator(BaseReportGenerator):
    name = "markdown"

    def __init__(self, config: dict):
        super().__init__(config)
        self._output_path = Path(config.get("output_path", "reports/"))
        self._include_summary: bool = config.get("include_summary", True)
        self._include_top_stories: bool = config.get("include_top_stories", True)
        self._include_by_source: bool = config.get("include_by_source", True)
        self._include_by_topic: bool = config.get("include_by_topic", True)
        self._top_count: int = config.get("top_stories_count", 10)

    def _generate(self, items: list[ProcessedItem], run_id: str) -> str:
        self._output_path.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        lines: list[str] = []
        lines.append(f"# Market Intelligence Report — {date_str}")
        lines.append("")
        lines.append(f"_Generated: {now.isoformat()}_")
        lines.append(f"_Run ID: `{run_id}`_")
        lines.append("")

        # Summary
        if self._include_summary:
            lines.append("## Summary")
            lines.append("")
            sources = Counter(item.source for item in items)
            sentiments = Counter(item.sentiment for item in items)
            all_keywords = [kw for item in items for kw in item.keywords]

            lines.append(f"| Metric | Value |")
            lines.append(f"|---|---|")
            lines.append(f"| Total items | {len(items)} |")
            lines.append(f"| Unique sources | {len(sources)} |")
            lines.append(f"| Positive sentiment | {sentiments.get('positive', 0)} |")
            lines.append(f"| Negative sentiment | {sentiments.get('negative', 0)} |")
            lines.append(f"| Neutral sentiment | {sentiments.get('neutral', 0)} |")
            lines.append("")

            if all_keywords:
                top_keywords = Counter(all_keywords).most_common(10)
                lines.append("**Top keywords:** " + ", ".join(f"`{kw}` ({count})" for kw, count in top_keywords))
                lines.append("")

        # Top stories
        if self._include_top_stories and items:
            lines.append("## Top Stories")
            lines.append("")
            # Sort by score (if available) then by source diversity
            sorted_items = sorted(items, key=lambda x: (x.score or 0), reverse=True)
            for i, item in enumerate(sorted_items[:self._top_count], 1):
                score_str = f" (score: {item.score})" if item.score else ""
                sentiment_emoji = {"positive": "📈", "negative": "📉", "neutral": "➖"}.get(item.sentiment, "")
                lines.append(f"### {i}. {item.title}")
                lines.append(f"**Source:** {item.source_name}{score_str} {sentiment_emoji}")
                lines.append(f"**Link:** [{item.url}]({item.url})")
                if item.body:
                    lines.append(f"\n> {item.body[:200]}{'...' if len(item.body) > 200 else ''}")
                if item.keywords:
                    lines.append(f"\n**Keywords:** {', '.join(f'`{kw}`' for kw in item.keywords)}")
                lines.append("")

        # By source
        if self._include_by_source and items:
            lines.append("## Items by Source")
            lines.append("")
            by_source: dict[str, list[ProcessedItem]] = defaultdict(list)
            for item in items:
                by_source[item.source_name].append(item)

            for source_name, source_items in sorted(by_source.items(), key=lambda x: len(x[1]), reverse=True):
                lines.append(f"### {source_name} ({len(source_items)})")
                lines.append("")
                for item in source_items[:5]:  # top 5 per source
                    lines.append(f"- [{item.title}]({item.url})")
                if len(source_items) > 5:
                    lines.append(f"- _...and {len(source_items) - 5} more_")
                lines.append("")

        # By topic (tag)
        if self._include_by_topic and items:
            lines.append("## Items by Topic")
            lines.append("")
            by_topic: dict[str, list[ProcessedItem]] = defaultdict(list)
            for item in items:
                for tag in item.tags:
                    by_topic[tag].append(item)

            for topic, topic_items in sorted(by_topic.items(), key=lambda x: len(x[1]), reverse=True):
                lines.append(f"### #{topic} ({len(topic_items)})")
                for item in topic_items[:3]:
                    lines.append(f"- [{item.title}]({item.url})")
                lines.append("")

        lines.append("---")
        lines.append(f"_Powered by [Market-Intel](https://github.com/marwangpt237/market-intel)_")

        content = "\n".join(lines)
        filepath = self._output_path / f"report_{date_str}.md"
        filepath.write_text(content, encoding="utf-8")

        self._logger.info(f"Report saved to {filepath}", extra={"file": str(filepath)})
        return str(filepath)
