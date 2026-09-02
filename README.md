# Distill

**An evidence-first reading list for engineers building with AI.**

Distill collects articles from the places you already follow, extracts their full text,
removes duplicates, and ranks what is genuinely worth your time. It favors production
experience, concrete mechanisms, measured results, and actions you can try—while penalizing
hype, repackaged consensus, and unsupported prediction.

The result is a focused weekly briefing you can read, export as Markdown, or turn into a
podcast.

![Distill's AI engineering briefing dashboard](docs/screenshot.png)

## Why Distill?

Keeping up with AI engineering is not a discovery problem anymore. It is a filtering problem.
Most feeds optimize for what is new or popular; Distill optimizes for what is useful to a
specific reader.

- **Personal, not generic** — describe the systems, problems, and outcomes you care about in a
  reader profile.
- **Evidence over excitement** — score relevance, technical depth, novelty, applicability, and
  evidence quality independently.
- **Action over awareness** — every strong recommendation includes a concrete next step.
- **Signal without a monoculture** — diversify by source, domain, and content similarity.
- **Transparent ranking** — inspect the score, rationale, and recommended action for every item.
- **One local workflow** — browse, search, add links, generate digests, and create podcasts from
  the same dashboard.

## How it works

```text
Collect → Extract → Deduplicate → Assess → Select → Digest → Podcast
   │         │           │           │         │         │         │
   │         │           │           │         │         │         └─ NotebookLM or edge-tts
   │         │           │           │         │         └─ Weekly Markdown briefing
   │         │           │           │         └─ Quality gates + diversity + relevant backfill
   │         │           │           └─ Claude judges evidence against your reader profile
   │         │           └─ Normalized URLs, title similarity, optional embeddings
   │         └─ trafilatura → readability-lxml → Jina Reader fallback
   └─ Hacker News, RSS, Dev.to, arXiv, Slack, and manually added links
```

The main briefing has two clear tiers:

1. **Recommendations** meet every configured quality threshold.
2. **More to explore** fills the requested reading-list size with the best remaining relevant
   articles, without presenting them as equally strong recommendations.

## Quick start

### Requirements

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- An Anthropic API key for article assessment and `edge-tts` podcast scripts

### Install and run

```bash
git clone https://github.com/ankitb7/distill.git
cd distill

uv sync
cp .env.example .env
# Add ANTHROPIC_API_KEY to .env

uv run distill init
uv run distill run
uv run distill serve
```

Open [http://localhost:8585](http://localhost:8585).

`distill run` performs collection, extraction, deduplication, assessment, and safe content
truncation. Later runs assess only new, stale, or retryable articles within the configured
assessment horizon.

## Make it yours

The useful part of Distill is not a universal ranking formula—it is the reader profile in
[`config.yaml`](config.yaml). Start with the outcomes you want to advance, then describe the
evidence you trust and the noise you want removed.

```yaml
reader_profile:
  mission: Find evidence-backed, actionable AI engineering practices.
  priority_outcomes:
    - build reliable internal coding-agent platforms
    - run repository-scale migrations with coordinated agents
    - improve frontend developer experience and CI pipelines
  positive_signals:
    - first-hand production case study with architecture and trade-offs
    - code, measurements, evaluations, incidents, or before-and-after results
    - a workflow, playbook, experiment, or decision framework we can reuse
  noise_signals:
    - prediction without evidence, mechanism, or an actionable decision
    - launch coverage, vendor marketing, listicles, and commentary on commentary
    - impressive demos without evaluation or production constraints
```

Then tune selection independently from assessment:

```yaml
scoring:
  model: claude-sonnet-4-5-20250929
  assessment_max_age_days: 45
  weights:
    engagement: 0.05
    relevance: 0.25
    technical_depth: 0.15
    novelty: 0.15
    applicability: 0.25
    evidence_quality: 0.15
    noise_penalty: 0.25

recommendation:
  minimum_score: 0.35
  minimum_relevance: 0.6
  minimum_applicability: 0.5
  minimum_evidence_quality: 0.4
  maximum_noise_penalty: 0.45
  fill_to_limit: true
  fallback_minimum_relevance: 0.4
  diversity_strength: 0.15
  max_per_domain: 2
```

See the checked-in configuration for the complete source, scoring, deduplication, web, and
podcast options.

## Sources

| Source | Default | Notes |
| --- | --- | --- |
| Hacker News | Enabled | Algolia discovery using configured keywords and engagement floor |
| RSS/Atom | Enabled | Curated feeds; article content is fetched during collection |
| Dev.to | Disabled | Tag-based discovery through the public API |
| arXiv | Disabled | Configurable research categories |
| Slack | Configurable | Token-based collection or Claude-mediated MCP ingestion |
| Manual links | Available | Paste URLs into the dashboard for immediate extraction |

RSS content is fetched at collection time so trusted subscriptions are not starved by
engagement-based extraction queues. Other sources use the same extraction stack during the
`extract` stage.

### Slack ingestion

Slack supports two backends:

- `token` collects autonomously with `slack-sdk` and a user token.
- `mcp` accepts `CollectedArticle` JSON prepared through your Slack MCP connection and ingests it
  with `distill ingest FILE`.

The collector rejects common non-article links such as meetings, issue trackers, documents, and
status pages. Trusted curators can be declared in the configuration and passed to the assessor as
context—not as a substitute for evidence.

## CLI

```bash
# Pipeline
uv run distill init
uv run distill collect [--source SOURCE]
uv run distill extract
uv run distill dedup [--embeddings]
uv run distill score [--rescore]
uv run distill run

# Outputs
uv run distill serve
uv run distill digest
uv run distill podcast [--articles 12,45,78]
uv run distill archive

# Utilities
uv run distill ingest FILE
uv run distill stats
uv run distill qa
```

Every command accepts `--config PATH` when you want to use a different profile. Run
`uv run distill COMMAND --help` for command-specific options.

## Web dashboard

- **Briefing** — prioritized recommendations, concrete next actions, and transparent assessments
- **Search** — search Hacker News and Dev.to, then add useful results directly
- **Add links** — bulk-ingest URLs with automatic extraction
- **Digests** — browse generated weekly Markdown briefings
- **Podcasts** — generate weekly or article-specific audio and listen in the browser
- **Stats** — inspect collection, extraction, deduplication, and scoring coverage

The interface supports light and dark themes, responsive layouts, keyboard navigation, labeled
controls, and reduced-motion preferences.

## Podcast providers

| Provider | How it works | Requirements |
| --- | --- | --- |
| `notebooklm` | Uploads a source document, requests an Audio Overview, and downloads it | Interactive `notebooklm login` session |
| `edge-tts` | Claude writes a two-host script; Microsoft voices synthesize the segments | `ANTHROPIC_API_KEY` |

Select the provider under `podcast.provider` in `config.yaml`. Podcast failures are surfaced in
the dashboard, and authentication failures explain how to reauthenticate.

> [!WARNING]
> `notebooklm-py` is an unofficial, reverse-engineered NotebookLM client—not an official Google
> API. It can break when Google changes the product and may be unsuitable for some environments.
> Review Google's terms before using it; choose `edge-tts` when this integration is unacceptable.

## Privacy and cost

Distill is local-first, but it is not fully offline:

- Article titles, URLs, extracted text, and configured reader-profile context are sent to
  Anthropic when Claude assessment is enabled.
- Slack-derived articles may contain internal context. Only enable Slack ingestion and scoring
  when sending that content to the configured model provider is permitted.
- Jina Reader receives article URLs only when local extraction fallbacks fail.
- NotebookLM receives the selected podcast source document when that provider is enabled.
- Extracted content remains the property of its authors and publishers. Distill is intended for
  personal curation; respect copyright and provider terms.

You are responsible for API usage, costs, data handling, and compliance with each provider's
terms.

## Architecture

```text
src/distill/
├── cli.py              Typer commands and local automation
├── config.py           YAML configuration and environment loading
├── models.py           Validated domain models
├── db.py               SQLite schema and persistence boundary
├── collectors/         Hacker News, RSS, Dev.to, arXiv, and Slack adapters
├── processing/         Extraction, deduplication, assessment, and slate selection
├── outputs/            Digest, podcast, and FastAPI web application
├── static/             Product assets
└── templates/          Jinja2 interface templates
```

SQLite runs in WAL mode. Network collection uses async `httpx`; assessment uses bounded
concurrency, exponential retry for transient failures, versioned scores, and durable writes after
each batch.

For the rationale behind the recommendation system, see
[`docs/article-recommendation-design.md`](docs/article-recommendation-design.md).

## Development

```bash
uv sync --group dev
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run pytest
```

Visual QA requires [`rodney`](https://github.com/simonw/rodney) and
[`showboat`](https://github.com/simonw/showboat):

```bash
uv run distill serve
uv run distill qa
```

## Disclaimer

This project is provided as-is, without warranty. The authors accept no liability for service
changes, terms-of-service issues, API costs, copyright claims, generated content, or data loss.
