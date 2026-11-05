"""REST API docs: JSON catalog (/api/docs) + human-readable page (/api-docs)."""
from app import apidocs


def test_api_docs_catalog(client):
    eps = client.get("/api/docs").json()
    assert isinstance(eps, list) and len(eps) >= 30
    keys = {(e["method"], e["path"]) for e in eps}
    # a sample from every functional group
    assert ("POST", "/api/login") in keys
    assert ("POST", "/api/import/map") in keys
    assert ("POST", "/api/collections/{id}/reimport") in keys
    assert ("PATCH", "/api/users/{id}") in keys
    assert ("GET", "/api/collections/{id}/rows") in keys
    assert ("POST", "/api/reminders/flush") in keys
    assert ("GET", "/api/docs") in keys
    for e in eps:
        assert e["role"] and e["group"] and e["description"]


def test_api_docs_catalog_covers_real_routes(client):
    """Every path template in the catalog exists as a registered route."""
    import re

    def norm(path):
        return re.sub(r"\{[^}]+\}", "{}", path)

    app = client.app
    real = {(next(iter(r.methods)), norm(r.path)) for r in app.routes
            if hasattr(r, "methods") and r.path.startswith("/api/")}
    documented = {(e["method"], norm(e["path"])) for e in apidocs.ENDPOINTS}
    missing = documented - real
    assert not missing, f"documented but not registered: {sorted(missing)}"


def test_api_docs_page_served(client):
    r = client.get("/api-docs")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "/api/docs" in r.text and "SheetFlow API" in r.text


def test_index_links_to_api_docs(client):
    html = client.get("/").text
    assert 'href="/api-docs"' in html
