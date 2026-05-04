from __future__ import annotations

import asyncio
import re
import warnings
from datetime import UTC, datetime, timedelta

from distill.models import CollectedArticle, Source

_URL_PATTERN = re.compile(r"<(https?://[^|>]+)(?:\|[^>]*)?>")
_SLACK_INTERNAL = re.compile(r"https?://[^/]*\.slack\.com/")
_NON_ARTICLE_PATTERNS = [
    re.compile(r"https?://meet\.google\.com/"),
    re.compile(r"https?://[^/]*zoom\.us/"),
    re.compile(r"https?://[^/]*\.atlassian\.net/"),
    re.compile(r"https?://[^/]*\.jira\.com/"),
    re.compile(r"https?://docs\.google\.com/"),
    re.compile(r"https?://drive\.google\.com/"),
    re.compile(r"https?://[^/]*loom\.com/"),
    re.compile(r"https?://status\.[^/]+"),
    re.compile(r"https?://[^/]*jamfselfservice://"),
]


def _is_non_article_url(url: str) -> bool:
    """Check if URL is a non-article link (meetings, internal tools, status pages, bare domains)."""
    from urllib.parse import urlparse

    for pattern in _NON_ARTICLE_PATTERNS:
        if pattern.match(url):
            return True
    parsed = urlparse(url)
    # Bare domain with no meaningful path (e.g. gravity.oplane.io, emdash.sh)
    if not parsed.path or parsed.path.rstrip("/") == "":
        return True
    return False


def extract_urls_from_text(text: str) -> list[str]:
    """Extract external article URLs from Slack mrkdwn-encoded message text."""
    urls = []
    for match in _URL_PATTERN.finditer(text):
        url = match.group(1)
        if _SLACK_INTERNAL.match(url):
            continue
        if _is_non_article_url(url):
            continue
        urls.append(url)
    return urls


def _fetch_channel_articles(
    client,  # slack_sdk.WebClient
    channel: dict,
    min_reactions: int,
    oldest_ts: str | None = None,
) -> list[CollectedArticle]:
    """Sync fetch of URL-containing messages from one Slack channel (token backend)."""
    from slack_sdk.errors import SlackApiError

    channel_id = channel.get("id") or channel.get("name")
    channel_name = channel.get("name", channel_id)

    api_kwargs: dict = {"channel": channel_id, "limit": 200}
    if oldest_ts:
        api_kwargs["oldest"] = oldest_ts

    try:
        response = client.conversations_history(**api_kwargs)
    except SlackApiError as e:
        warnings.warn(f"Slack API error for channel {channel_id}: {e}", stacklevel=2)
        return []

    messages = response.get("messages", [])
    seen_urls: set[str] = set()
    articles: list[CollectedArticle] = []

    for msg in messages:
        if msg.get("subtype"):
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
            return []

        # backend == "token"
        token = slack_config.get("token")
        if not token:
            return []

        from slack_sdk import WebClient

        client = WebClient(token=token)
        min_reactions = slack_config.get("min_reactions", 0)
        max_results = slack_config.get("max_results", 50)

        max_age_days = slack_config.get("max_age_days")
        oldest_ts: str | None = None
        if max_age_days:
            cutoff = datetime.now(UTC) - timedelta(days=int(max_age_days))
            oldest_ts = str(cutoff.timestamp())

        tasks = [
            asyncio.to_thread(
                _fetch_channel_articles,
                client,
                ch if isinstance(ch, dict) else {"id": ch},
                min_reactions,
                oldest_ts,
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
