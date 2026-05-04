import re

import httpx
import trafilatura
from readability import Document

from distill.db import Database
from distill.models import Article

_TWEET_URL = re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/\w+/status/\d+")
_URL_IN_TEXT = re.compile(r"https?://[^\s\)\]>\"\']+")


def extract_article_urls_from_text(text: str) -> list[str]:
    """Extract non-tweet HTTP URLs from plain text (tweet body, feed summary, etc.)."""
    urls = []
    for match in _URL_IN_TEXT.finditer(text):
        url = match.group().rstrip(".,;)'\"")
        if _TWEET_URL.match(url):
            continue
        if "jina.ai" in url:
            continue
        urls.append(url)
    return urls


async def resolve_tweet_url(
    client: httpx.AsyncClient, url: str, hint_text: str | None = None
) -> str:
    """
    For a tweet URL, return the article URL embedded in the tweet.
    Tries hint_text (feedparser summary/content) first — no HTTP call needed.
    Falls back to Jina Reader to fetch the tweet and extract the link.
    Returns the original URL if no article link is found.
    """
    if not _TWEET_URL.match(url):
        return url

    if hint_text:
        candidates = extract_article_urls_from_text(hint_text)
        if candidates:
            return candidates[0]

    try:
        resp = await client.get(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "text/plain", "X-Return-Format": "text"},
        )
        resp.raise_for_status()
        candidates = extract_article_urls_from_text(resp.text)
        if candidates:
            return candidates[0]
    except Exception:
        pass

    return url


async def extract_content(db: Database, limit: int = 50) -> int:
    articles = db.get_articles_without_content(limit=limit)
    extracted = 0

    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": "distill/0.1 (article curation bot)"},
    ) as client:
        for article in articles:
            resolved_url = await resolve_tweet_url(client, article.url)
            if resolved_url != article.url:
                db.update_url(article.id, resolved_url)
                article = article.model_copy(update={"url": resolved_url})
            content = await fetch_article_content(client, article.url)
            if content:
                db.update_content(article.id, content)
                extracted += 1

    return extracted


async def fetch_article_content(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text.translate({i: None for i in range(32) if i not in (9, 10, 13)})
        content = parse_html_to_text(html)
        if content:
            return content
    except Exception:
        pass

    try:
        resp = await client.get(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "text/plain", "X-Return-Format": "text"},
        )
        resp.raise_for_status()
        content = resp.text.strip()
        if content and len(content) > 100:
            return content
    except Exception:
        pass

    return None


async def _extract_single(client: httpx.AsyncClient, article: Article) -> str | None:
    return await fetch_article_content(client, article.url)


def parse_html_to_text(html: str) -> str | None:
    content = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    if content and len(content) > 100:
        return content

    try:
        doc = Document(html)
        content = trafilatura.extract(doc.summary()) or _strip_tags(doc.summary())
        if content and len(content) > 100:
            return content
    except Exception:
        pass

    return None


def _strip_tags(html: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", html)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean
