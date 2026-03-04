from __future__ import annotations

import asyncio
import re
import warnings
from datetime import datetime

from distill.models import CollectedArticle, Source

_URL_PATTERN = re.compile(r"<(https?://[^|>]+)(?:\|[^>]*)?>")
_SLACK_INTERNAL = re.compile(r"https?://[^/]*\.slack\.com/")


def extract_urls_from_text(text: str) -> list[str]:
    """Extract external URLs from Slack mrkdwn-encoded message text."""
    urls = []
    for match in _URL_PATTERN.finditer(text):
        url = match.group(1)
        if not _SLACK_INTERNAL.match(url):
            urls.append(url)
    return urls


def _fetch_channel_articles(
    client,  # slack_sdk.WebClient
    channel: dict,
    min_reactions: int,
) -> list[CollectedArticle]:
    """Sync fetch of URL-containing messages from one Slack channel (token backend)."""
    from slack_sdk.errors import SlackApiError

    channel_id = channel.get("id") or channel.get("name")
    channel_name = channel.get("name", channel_id)

    try:
        response = client.conversations_history(channel=channel_id, limit=200)
    except SlackApiError as e:
        warnings.warn(f"Slack API error for channel {channel_id}: {e}", stacklevel=2)
        return []

    messages = response.get("messages", [])
    seen_urls: set[str] = set()
    articles: list[CollectedArticle] = []

    for msg in messages:
        if msg.get("subtype"):  # skip bot/join/leave messages
            continue

        text = msg.get("text", "")
        urls = extract_urls_from_text(text)
        if not urls:
            continue

        total_reactions = sum(r.get("count", 0) for r in msg.get("reactions", []))
        if total_reactions < min_reactions:
            continue

        ts = msg.get("ts", "")
        published_at = datetime.fromtimestamp(float(ts)) if ts else None
        author = msg.get("user") or msg.get("username", "unknown")
        reply_count = msg.get("reply_count", 0)
        title = re.sub(r"<[^>]+>", "", text).strip()[:120]

        for url in urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            articles.append(
                CollectedArticle(
                    url=url,
                    title=title or url,
                    author=author,
                    source=Source.SLACK,
                    source_id=ts,
                    published_at=published_at,
                    tags=[channel_name] if channel_name else [],
                    points=total_reactions,
                    comment_count=reply_count,
                    summary=text[:500] if len(text) > 120 else None,
                )
            )
    return articles


class SlackCollector:
    source_name = "slack"

    async def collect(self, config: dict) -> list[CollectedArticle]:
        slack_config = config.get("sources", {}).get("slack", {})
        if not slack_config.get("enabled", False):
            return []

        backend = slack_config.get("backend", "mcp")
        channels = slack_config.get("channels", [])
        if not channels:
            return []

        if backend == "mcp":
            # MCP backend is Claude-mediated: use `distill ingest` instead.
            # This collector is intentionally a no-op in automated runs.
            return []

        # backend == "token"
        token = slack_config.get("token")
        if not token:
            return []

        from slack_sdk import WebClient  # lazy import; only needed for token backend

        client = WebClient(token=token)
        min_reactions = slack_config.get("min_reactions", 0)
        max_results = slack_config.get("max_results", 50)

        tasks = [
            asyncio.to_thread(
                _fetch_channel_articles,
                client,
                ch if isinstance(ch, dict) else {"id": ch},
                min_reactions,
            )
            for ch in channels
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        articles: list[CollectedArticle] = []
        for result in results:
            if isinstance(result, Exception):
                continue
            articles.extend(result)

        return articles[:max_results]
