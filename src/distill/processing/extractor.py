import httpx
import trafilatura
from readability import Document

from distill.db import Database
from distill.models import Article


async def extract_content(db: Database, limit: int = 50) -> int:
    articles = db.get_articles_without_content(limit=limit)
    extracted = 0

    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": "distill/0.1 (article curation bot)"},
    ) as client:
        for article in articles:
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
    import re

    clean = re.sub(r"<[^>]+>", " ", html)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean
