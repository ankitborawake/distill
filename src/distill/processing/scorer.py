"""Article scoring: engagement normalization + Claude LLM-as-judge."""

import json
import os
from statistics import mean, stdev
from urllib.parse import urlparse

import httpx

from distill.db import Database
from distill.models import Article, ScoreBreakdown


def _extract_rss_domains(config: dict) -> set[str]:
    """Extract domains from RSS feed URLs in config as trusted author sources."""
    domains = set()
    feeds = config.get("sources", {}).get("rss", {}).get("feeds", [])
    for feed in feeds:
        url = feed.get("url", "")
        if url:
            domain = urlparse(url).netloc.removeprefix("www.")
            domains.add(domain)
    return domains


def _extract_rss_authors(config: dict) -> dict[str, str]:
    """Extract domain -> author name mapping from RSS feeds."""
    authors = {}
    feeds = config.get("sources", {}).get("rss", {}).get("feeds", [])
    for feed in feeds:
        url = feed.get("url", "")
        name = feed.get("name", "")
        if url and name:
            domain = urlparse(url).netloc.removeprefix("www.")
            authors[domain] = name
    return authors


def _get_trusted_curators(config: dict) -> dict[str, str]:
    """Get trusted Slack curators from config: {user_id: name}."""
    curators = {}
    slack_config = config.get("sources", {}).get("slack", {})
    for curator in slack_config.get("trusted_curators", []):
        curators[curator["id"]] = curator["name"]
    return curators


def _get_interest_keywords(config: dict) -> list[str]:
    """Extract the user's interest keywords from HN config."""
    return config.get("sources", {}).get("hackernews", {}).get("keywords", [])


def compute_engagement_score(article: Article, all_articles: list[Article]) -> float:
    if article.points is None and article.comment_count is None:
        return 0.5

    points = [a.points for a in all_articles if a.points is not None]
    comments = [a.comment_count for a in all_articles if a.comment_count is not None]

    if not points or len(points) < 2:
        return 0.5

    p_mean = mean(points)
    p_std = stdev(points) if len(points) > 1 else 1.0
    c_mean = mean(comments) if comments else 0
    c_std = stdev(comments) if len(comments) > 1 else 1.0

    p_z = ((article.points or 0) - p_mean) / max(p_std, 1)
    c_z = ((article.comment_count or 0) - c_mean) / max(c_std, 1)

    raw = 0.6 * p_z + 0.4 * c_z
    return max(0.0, min(1.0, (raw + 2) / 4))


async def _fetch_web_signals(url: str, trusted_domains: set[str]) -> dict:
    """Search HN Algolia API + check URL domain for reputation signals."""
    signals: dict = {"hn_points": 0, "hn_comments": 0, "hn_stories": 0, "domain_note": ""}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://hn.algolia.com/api/v1/search",
                params={"query": url, "tags": "story", "hitsPerPage": 5},
            )
            if resp.status_code == 200:
                data = resp.json()
                hits = data.get("hits", [])
                signals["hn_stories"] = len(hits)
                if hits:
                    signals["hn_points"] = max(h.get("points", 0) or 0 for h in hits)
                    signals["hn_comments"] = max(h.get("num_comments", 0) or 0 for h in hits)
    except Exception:
        pass

    domain = urlparse(url).netloc.removeprefix("www.")
    if domain in trusted_domains:
        signals["domain_note"] = f"Trusted source (in user's RSS subscriptions): {domain}"

    return signals


def _build_slack_prompt(
    article: Article,
    web_signals: dict,
    interest_keywords: list[str],
    rss_authors: dict[str, str],
    trusted_curators: dict[str, str],
) -> str:
    """Build a Slack-specific scoring prompt driven by user's config preferences."""
    content_preview = (article.content_text or "")[:3000]
    slack_context = article.summary or article.title or ""

    # Build context sections
    web_context_parts = []
    if web_signals["hn_stories"] > 0:
        web_context_parts.append(
            f"- Hacker News: {web_signals['hn_stories']} stories, "
            f"top had {web_signals['hn_points']} points and {web_signals['hn_comments']} comments"
        )
    if web_signals["domain_note"]:
        web_context_parts.append(f"- {web_signals['domain_note']}")

    # Check if article domain matches an RSS author
    domain = urlparse(article.url).netloc.removeprefix("www.")
    if domain in rss_authors:
        web_context_parts.append(
            f"- Author signal: this domain belongs to {rss_authors[domain]}, "
            f"who the user explicitly subscribes to via RSS"
        )

    # Check if shared by a trusted curator
    curator_name = trusted_curators.get(article.author or "")
    if curator_name:
        web_context_parts.append(
            f"- Curator signal: shared by {curator_name}, a trusted curator in this channel"
        )

    web_context = ""
    if web_context_parts:
        web_context = "\nReputation & virality signals:\n" + "\n".join(web_context_parts) + "\n"

    # Format interest topics as a semantic profile, not a keyword list
    keywords_str = ", ".join(interest_keywords) if interest_keywords else ""

    return f"""You are scoring a URL shared in an internal Slack channel for AI/coding practitioners.
Evaluate THE LINKED ARTICLE/RESOURCE (not the Slack message itself).

The reader is a senior software engineer whose interests are:
{keywords_str}

These are NOT literal filters — they describe the SEMANTIC SPACE of what this person cares about. \
An article doesn't need to mention these exact terms. Score high if the article's substance falls \
within or adjacent to these interests. Score low if it's outside this space entirely (entertainment, \
company logistics, general tech news without AI/engineering depth, social commentary).

URL: {article.url}
Slack context (how it was shared): {slack_context}
{f"Article content:{chr(10)}{content_preview}" if content_preview else "No article content available — evaluate based on URL, domain reputation, and your knowledge of this resource."}
{web_context}
Score on three axes from 0.0 to 1.0:

1. technical_depth: How substantive is the actual content at this URL?
   0.0 = tweet, meme, shallow take, product landing page, announcement with no substance
   0.5 = blog post with some analysis, tool README with good docs
   1.0 = deep technical dive with code, architecture decisions, methodology, or research

2. novelty: How fresh or unique is this within the reader's interest space?
   0.0 = widely covered news, obvious take, rehash of known ideas
   0.5 = interesting angle on known topic, useful tool in established category
   1.0 = genuinely new technique, contrarian insight backed by evidence, breakthrough tool

3. applicability: Could the reader directly use this in their AI-augmented engineering work THIS WEEK?
   0.0 = entertainment, fun projects, jokes, company logistics, philosophical takes, social commentary
   0.2 = interesting to read but no actionable takeaway
   0.5 = useful reference, tool in a niche they might use someday
   0.7 = practical technique, tool, or workflow they could adopt soon
   1.0 = immediately actionable: install this tool today, apply this technique in next PR

   STRICT rules for applicability:
   - Fun/novelty projects (games, art, jokes built with AI) = 0.0-0.1 regardless of technical quality
   - "Look what AI can do" demos = 0.1-0.2
   - Opinion pieces / essays about AI trends = 0.1-0.3 (reading ≠ applying)
   - Tool announcements with install instructions = 0.5-0.8
   - Workflow patterns with step-by-step guide = 0.7-1.0

Reputation matters: articles from trusted RSS authors or shared by trusted curators \
deserve a slight boost (+0.1) to novelty, since these curators have a track record of \
finding high-signal content. But substance still trumps reputation — a shallow link from \
a trusted source is still shallow.

Be VERY strict. Most shared links deserve low scores. A viral tweet is still just a tweet.

Respond in JSON only:
{{"technical_depth": 0.X, "novelty": 0.X, "applicability": 0.X, "reasoning": "1-2 sentences about the actual article quality"}}"""  # noqa: E501


async def score_with_llm(
    articles: list[Article],
    model: str = "claude-sonnet-4-5-20250929",
    config: dict | None = None,
) -> dict[int, ScoreBreakdown]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {}

    config = config or {}
    interest_keywords = _get_interest_keywords(config)
    rss_authors = _extract_rss_authors(config)
    trusted_curators = _get_trusted_curators(config)
    trusted_domains = _extract_rss_domains(config)

    results = {}
    for article in articles:
        is_slack = article.source.value == "slack"

        if is_slack:
            web_signals = await _fetch_web_signals(article.url, trusted_domains)
            prompt = _build_slack_prompt(
                article,
                web_signals,
                interest_keywords,
                rss_authors,
                trusted_curators,
            )
        else:
            content_preview = (article.content_text or "")[:3000]
            if not content_preview:
                continue

            prompt = f"""Rate this article for a senior software engineer who heavily uses AI \
(Claude Code, coding agents, agentic workflows) in daily work.

The ideal article is about: practical AI adoption patterns, agentic engineering, \
AI-augmented development workflows, coding agents, LLM integration in production, \
career strategy for AI-era engineers, or deep technical dives with actionable takeaways.

Low-value: pure hype/funding news, surface-level overviews, theoretical ML papers \
without practical application, listicles.

Title: {article.title}
Source: {article.source.value}
Content (preview):
{content_preview}

Rate on three axes from 0.0 to 1.0:
1. technical_depth: 0=news rewrite/summary, 1=deep analysis with code, architecture, or methodology
2. novelty: 0=widely covered/obvious, 1=fresh perspective, new technique, or contrarian insight
3. applicability: 0=theoretical/hype, 1=I could apply this at work Monday morning

Respond in JSON only:
{{"technical_depth": 0.X, "novelty": 0.X, "applicability": 0.X, "reasoning": "brief"}}"""

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "max_tokens": 256,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["content"][0]["text"]
                text = text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0]
                parsed = json.loads(text)
                results[article.id] = ScoreBreakdown(
                    technical_depth=float(parsed.get("technical_depth", 0)),
                    novelty=float(parsed.get("novelty", 0)),
                    applicability=float(parsed.get("applicability", 0)),
                    reasoning=parsed.get("reasoning", ""),
                )
        except Exception:
            continue

    return results


async def score_articles(db: Database, config: dict) -> int:
    scoring_config = config.get("scoring", {})
    model = scoring_config.get("model", "claude-sonnet-4-5-20250929")
    weights = scoring_config.get("weights", {})
    min_engagement = scoring_config.get("min_engagement_for_llm", 5)
    min_engagement_by_source = scoring_config.get("min_engagement_by_source", {})
    batch_size = scoring_config.get("batch_size", 5)

    w_eng = weights.get("engagement", 0.20)
    w_td = weights.get("technical_depth", 0.25)
    w_nov = weights.get("novelty", 0.25)
    w_app = weights.get("applicability", 0.30)

    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    unscored = db.get_unscored_articles(min_engagement=0, require_content=False)
    all_articles = db.get_all_articles(non_duplicate_only=True)

    scored_count = 0

    # Manually added articles get the highest score automatically
    manual = [a for a in unscored if "manual" in (a.tags or [])]
    manual_ids = {a.id for a in manual}
    for article in manual:
        score = ScoreBreakdown(
            engagement_score=1.0,
            technical_depth=1.0,
            novelty=1.0,
            applicability=1.0,
            composite_score=1.0,
            reasoning="Manually added — auto-scored highest",
        )
        db.insert_score(article.id, score)
        scored_count += 1

    unscored = [a for a in unscored if a.id not in manual_ids]

    if has_api_key:
        llm_eligible = [
            a
            for a in unscored
            if a.source.value == "slack"  # Slack: always LLM-score, even without content_text
            or (
                a.content_text
                and (
                    (a.points or 0) >= min_engagement_by_source.get(a.source.value, min_engagement)
                    or a.points is None
                )
            )
        ]
        llm_ids = {a.id for a in llm_eligible}
        engagement_only = [a for a in unscored if a.id not in llm_ids]
    else:
        llm_eligible = []
        engagement_only = unscored

    for article in engagement_only:
        eng = compute_engagement_score(article, all_articles)
        # Cap engagement-only at 0.4 so they never outrank LLM-scored articles
        composite = min(eng * w_eng / max(w_eng, 0.01), 0.4)
        score = ScoreBreakdown(
            engagement_score=eng,
            composite_score=composite,
            reasoning="Engagement-only (no LLM scoring)",
        )
        db.insert_score(article.id, score)
        scored_count += 1

    for i in range(0, len(llm_eligible), batch_size):
        batch = llm_eligible[i : i + batch_size]
        llm_scores = await score_with_llm(batch, model=model, config=config)

        for article in batch:
            eng = compute_engagement_score(article, all_articles)
            llm = llm_scores.get(article.id)

            if llm:
                if article.source.value == "slack":
                    # Slack: minimize engagement, maximize content quality signals
                    composite = (
                        0.05 * eng
                        + 0.25 * llm.technical_depth
                        + 0.30 * llm.novelty
                        + 0.40 * llm.applicability
                    )
                else:
                    composite = (
                        w_eng * eng
                        + w_td * llm.technical_depth
                        + w_nov * llm.novelty
                        + w_app * llm.applicability
                    )
                score = ScoreBreakdown(
                    engagement_score=eng,
                    technical_depth=llm.technical_depth,
                    novelty=llm.novelty,
                    applicability=llm.applicability,
                    composite_score=composite,
                    reasoning=llm.reasoning,
                )
            else:
                score = ScoreBreakdown(
                    engagement_score=eng,
                    composite_score=eng,
                    reasoning="LLM scoring failed, engagement-only",
                )
            db.insert_score(article.id, score)
            scored_count += 1

    return scored_count
