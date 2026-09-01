# Distill

Distill curates technical articles into ranked weekly digests and podcasts for senior engineers
adopting AI in their work.

## Language

**Article**:
A link and its collected metadata, extracted content, engagement signals, and optional score as it
moves through Collect → Extract → Dedup → Score → Digest → Podcast.
_Avoid_: Item, post, resource

**Article intake**:
The workflow that validates and persists externally supplied articles outside automated Collect
sources. It includes bulk JSON ingestion and manual article enrichment.
_Avoid_: Import pipeline, ad hoc insert

**Manual article**:
An article explicitly selected through the Web interface, always tagged `manual` so Podcast treats
it as required coverage. Manual articles are enriched during article intake.
_Avoid_: Pinned link, forced article

## Example dialogue

> **Developer:** Does a URL pasted into Add Links go through Collect?
>
> **Domain expert:** No. Article intake creates a Manual article, extracts its content, and tags it
> for required Podcast coverage. Collect remains the automated source workflow.
