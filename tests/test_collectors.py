import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from distill.collectors.hackernews import HackerNewsCollector
from distill.collectors.rss import RSSCollector


@pytest.mark.asyncio
async def test_hackernews_collector_disabled():
    collector = HackerNewsCollector()
    config = {"sources": {"hackernews": {"enabled": False}}}
    articles = await collector.collect(config)
    assert articles == []


@pytest.mark.asyncio
async def test_hackernews_recency_filter_applied():
    """created_at_i filter is included in the Algolia query params."""
    collector = HackerNewsCollector()
    config = {"sources": {"hackernews": {"enabled": True, "keywords": ["AI"], "max_age_days": 7}}}

    captured_params = {}

    async def fake_get(url, params=None):
        captured_params.update(params or {})
        mock = AsyncMock()
        mock.raise_for_status = lambda: None
        mock.json.return_value = {"hits": []}
        return mock

    with patch("distill.collectors.hackernews.httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get = fake_get
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await collector.collect(config)

    assert "numericFilters" in captured_params
    assert "created_at_i>" in captured_params["numericFilters"]


@pytest.mark.asyncio
async def test_hackernews_default_max_age_days():
    """Default max_age_days of 30 is used when not configured."""
    collector = HackerNewsCollector()
    config = {"sources": {"hackernews": {"enabled": True, "keywords": ["AI"]}}}

    captured_params = {}

    async def fake_get(url, params=None):
        captured_params.update(params or {})
        mock = AsyncMock()
        mock.raise_for_status = lambda: None
        mock.json.return_value = {"hits": []}
        return mock

    with patch("distill.collectors.hackernews.httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get = fake_get
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        await collector.collect(config)

    filters = captured_params.get("numericFilters", "")
    match = re.search(r"created_at_i>(\d+)", filters)
    assert match, "created_at_i filter missing"
    from datetime import UTC, datetime, timedelta
    min_ts = int(match.group(1))
    age = datetime.now(UTC).timestamp() - min_ts
    assert 29 * 86400 < age < 31 * 86400, f"Expected ~30 days, got {age/86400:.1f} days"


@pytest.mark.asyncio
async def test_rss_collector_disabled():
    collector = RSSCollector()
    config = {"sources": {"rss": {"enabled": False}}}
    articles = await collector.collect(config)
    assert articles == []


@pytest.mark.asyncio
async def test_rss_collector_empty_feeds():
    collector = RSSCollector()
    config = {"sources": {"rss": {"enabled": True, "feeds": []}}}
    articles = await collector.collect(config)
    assert articles == []
