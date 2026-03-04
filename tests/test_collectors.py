from unittest.mock import MagicMock

import pytest

from distill.collectors.hackernews import HackerNewsCollector
from distill.collectors.rss import RSSCollector
from distill.collectors.slack import SlackCollector, _fetch_channel_articles, extract_urls_from_text
from distill.models import Source


def test_slack_source_enum_value():
    assert Source.SLACK == "slack"


def test_extract_urls_bare():
    assert extract_urls_from_text("Check <https://example.com>") == ["https://example.com"]


def test_extract_urls_with_label():
    assert extract_urls_from_text("<https://example.com/a|Great Article>") == ["https://example.com/a"]


def test_extract_urls_multiple():
    assert extract_urls_from_text("<https://a.com> and <https://b.com|B>") == ["https://a.com", "https://b.com"]


def test_extract_urls_none():
    assert extract_urls_from_text("no links here") == []


def test_extract_urls_skips_slack_internal():
    assert extract_urls_from_text("<https://yourworkspace.slack.com/archives/C123>") == []


@pytest.mark.asyncio
async def test_slack_collector_disabled():
    collector = SlackCollector()
    config = {"sources": {"slack": {"enabled": False}}}
    articles = await collector.collect(config)
    assert articles == []


@pytest.mark.asyncio
async def test_slack_collector_missing_config():
    collector = SlackCollector()
    config = {"sources": {}}
    articles = await collector.collect(config)
    assert articles == []


@pytest.mark.asyncio
async def test_slack_collector_mcp_backend_returns_empty():
    """MCP backend is Claude-mediated; collect() is a no-op."""
    collector = SlackCollector()
    config = {
        "sources": {
            "slack": {
                "enabled": True,
                "backend": "mcp",
                "channels": [{"id": "C123", "name": "eng"}],
            }
        }
    }
    articles = await collector.collect(config)
    assert articles == []


@pytest.mark.asyncio
async def test_slack_collector_token_backend_no_token():
    collector = SlackCollector()
    config = {
        "sources": {
            "slack": {
                "enabled": True,
                "backend": "token",
                "channels": [{"id": "C123", "name": "eng"}],
                # no token
            }
        }
    }
    articles = await collector.collect(config)
    assert articles == []


@pytest.mark.asyncio
async def test_slack_collector_no_channels():
    collector = SlackCollector()
    config = {
        "sources": {
            "slack": {
                "enabled": True,
                "backend": "token",
                "token": "xoxp-test",
                "channels": [],
            }
        }
    }
    articles = await collector.collect(config)
    assert articles == []


@pytest.mark.asyncio
async def test_hackernews_collector_disabled():
    collector = HackerNewsCollector()
    config = {"sources": {"hackernews": {"enabled": False}}}
    articles = await collector.collect(config)
    assert articles == []


@pytest.mark.asyncio
async def test_rss_collector_disabled():
    collector = RSSCollector()
    config = {"sources": {"rss": {"enabled": False}}}
    articles = await collector.collect(config)
    assert articles == []


def _make_slack_client(messages: list[dict]) -> MagicMock:
    client = MagicMock()
    client.conversations_history.return_value = {
        "ok": True,
        "messages": messages,
        "has_more": False,
    }
    return client


def test_fetch_channel_articles_extracts_url():
    msg = {
        "ts": "1700000000.000001",
        "user": "U123",
        "text": "Read this <https://example.com/article|Great Post>",
        "reactions": [{"name": "thumbsup", "count": 3}],
        "reply_count": 1,
    }
    articles = _fetch_channel_articles(_make_slack_client([msg]), {"id": "C123", "name": "general"}, 0)
    assert len(articles) == 1
    assert articles[0].url == "https://example.com/article"
    assert articles[0].points == 3
    assert articles[0].comment_count == 1
    assert articles[0].source_id == "1700000000.000001"
    assert articles[0].tags == ["general"]


def test_fetch_channel_articles_filters_by_min_reactions():
    msg = {
        "ts": "1700000000.000001",
        "user": "U123",
        "text": "<https://example.com>",
        "reactions": [{"name": "thumbsup", "count": 1}],
    }
    articles = _fetch_channel_articles(_make_slack_client([msg]), {"id": "C123", "name": "general"}, 2)
    assert articles == []


def test_fetch_channel_articles_skips_bot_messages():
    msg = {"ts": "1700000000.000001", "subtype": "bot_message", "text": "<https://example.com>", "reactions": [{"name": "+1", "count": 5}]}
    articles = _fetch_channel_articles(_make_slack_client([msg]), {"id": "C123"}, 0)
    assert articles == []


def test_fetch_channel_articles_deduplicates_urls():
    msg = {"ts": "1700000000.000001", "user": "U123", "text": "<https://example.com> and <https://example.com>", "reactions": []}
    articles = _fetch_channel_articles(_make_slack_client([msg]), {"id": "C123"}, 0)
    assert len(articles) == 1


@pytest.mark.asyncio
async def test_rss_collector_empty_feeds():
    collector = RSSCollector()
    config = {"sources": {"rss": {"enabled": True, "feeds": []}}}
    articles = await collector.collect(config)
    assert articles == []
