"""Favicon + OG meta tags served with the SPA."""


def test_favicon_served(client):
    r = client.get("/static/favicon.svg")
    assert r.status_code == 200
    assert "image/svg" in r.headers["content-type"]
    assert b"<svg" in r.content


def test_index_has_favicon_and_og_meta(client):
    html = client.get("/").text
    assert 'rel="icon"' in html and "/static/favicon.svg" in html
    assert 'property="og:title"' in html
    assert 'property="og:description"' in html
    assert 'name="description"' in html
