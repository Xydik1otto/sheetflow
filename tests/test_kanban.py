"""Kanban view backend contract: statuses are free-form, PATCH moves cards."""


def test_patch_status_moves_row_between_columns(client, imported_collection):
    rows = client.get(f"/api/collections/{imported_collection}/rows").json()
    rid = rows[0]["id"]
    for st in ("in_progress", "blocked", "done", "new"):
        r = client.patch(f"/api/rows/{rid}", json={"field": "status", "value": st})
        assert r.status_code == 200
        rows_now = client.get(f"/api/collections/{imported_collection}/rows?status={st}").json()
        assert any(x["id"] == rid for x in rows_now)


def test_custom_status_allowed_for_kanban_column(client, imported_collection):
    """Kanban columns = default statuses + whatever statuses exist in data."""
    rows = client.get(f"/api/collections/{imported_collection}/rows").json()
    rid = rows[0]["id"]
    r = client.patch(f"/api/rows/{rid}", json={"field": "status", "value": "verification"})
    assert r.status_code == 200
    rows_now = client.get(f"/api/collections/{imported_collection}/rows").json()
    assert "verification" in {x["status"] for x in rows_now}


def test_status_filter_and_counts(client, imported_collection):
    rows = client.get(f"/api/collections/{imported_collection}/rows").json()
    rid = rows[0]["id"]
    client.patch(f"/api/rows/{rid}", json={"field": "status", "value": "done"})
    done = client.get(f"/api/collections/{imported_collection}/rows?status=done").json()
    assert all(x["status"] == "done" for x in done)
    assert any(x["id"] == rid for x in done)
