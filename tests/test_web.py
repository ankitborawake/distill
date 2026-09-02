import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from distill.db import Database
from distill.models import CollectedArticle, Source
from distill.outputs.web import create_app


def _make_config(db_path: Path) -> dict:
    return {
        "database": {"path": str(db_path)},
        "output": {"dir": str(db_path.parent / "output")},
    }


def test_index_empty_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    db = Database(db_path)
    db.init_schema()
    db.close()

    config = _make_config(db_path)
    # Patch get_db_path to return our temp path
    app = create_app(config)
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Distill" in resp.text


def test_index_with_articles():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    db = Database(db_path)
    db.init_schema()
    article = CollectedArticle(
        url="https://example.com/web-test",
        title="Web Test Article",
        source=Source.HACKERNEWS,
        points=42,
    )
    aid = db.insert_article(article)
    db.update_content(aid, "Test content " * 50)
    db.close()

    config = _make_config(db_path)
    app = create_app(config)
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Web Test Article" in resp.text

    resp = client.get(f"/article/{aid}")
    assert resp.status_code == 200
    assert "Web Test Article" in resp.text


def test_index_uses_plain_text_content_when_summary_is_missing():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    db = Database(db_path)
    db.init_schema()
    article = CollectedArticle(
        url="https://example.com/hn-summary",
        title="HN Article",
        source=Source.HACKERNEWS,
    )
    article_id = db.insert_article(article)
    db.update_content(article_id, "A useful extracted description for this Hacker News article.")
    db.close()

    resp = TestClient(create_app(_make_config(db_path))).get("/")

    assert "A useful extracted description for this Hacker News article." in resp.text


def test_index_strips_html_from_stored_summary():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    db = Database(db_path)
    db.init_schema()
    article = CollectedArticle(
        url="https://example.com/rss-summary",
        title="RSS Article",
        source=Source.RSS,
        summary="<p>A <strong>useful</strong> summary &amp; description.</p>",
        content_text="Extracted article content.",
        content_length=26,
    )
    db.insert_article(article)
    db.close()

    resp = TestClient(create_app(_make_config(db_path))).get("/")

    assert "A useful summary &amp; description." in resp.text
    assert "&lt;p&gt;" not in resp.text


def test_stats_page():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    db = Database(db_path)
    db.init_schema()
    db.close()

    config = _make_config(db_path)
    app = create_app(config)
    client = TestClient(app)
    resp = client.get("/stats")
    assert resp.status_code == 200


def test_article_not_found():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    db = Database(db_path)
    db.init_schema()
    db.close()

    config = _make_config(db_path)
    app = create_app(config)
    client = TestClient(app)
    resp = client.get("/article/99999")
    assert resp.status_code == 404
