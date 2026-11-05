# Contributing to SheetFlow

Thank you for your interest in SheetFlow! Contributions of every kind are
welcome: bug reports, ideas, translations, code.

> Українська версія: [CONTRIBUTING.md](CONTRIBUTING.md) — mirror of this
> document.

## Languages

The UI and docs are **Ukrainian and English**. Russian localization is not
accepted — a deliberate decision of the project owner; such PRs are closed
without discussion. The test
`tests/test_i18n.py::test_no_russian_in_i18n_and_ui` automatically rejects
Russian-specific letters (see the [i18n](#i18n-ua--en) section below).

## How to report a bug

1. Check whether the problem already exists in [issues](../../issues).
2. Open a new issue using the **Bug report** template — it is in English and
   Ukrainian; write in either language.
3. Include: Python version, OS, steps to reproduce, expected/actual result.

## Feature requests

Use the **Feature request** template: describe the problem the feature
solves, not just "I want a button".

## How the code works

SheetFlow is FastAPI + sqlite3 (no ORM); the frontend is vanilla JS with no
build step in `app/static/`. The key idea: **import the user's process,
don't force them to change it**.

### `app/importer.py` — xlsx/CSV parsing and column mapping

The import pipeline has four steps; they are identical for `.xlsx`
(openpyxl) and `.csv`, because both formats are reduced to rows of tuples
via `iter_rows()`:

1. **Format detection and decoding.**
   - `is_xlsx()`: an xlsx is a ZIP archive, recognized by the `PK` signature;
   - `detect_encoding()` for text uploads: BOM → `utf-8-sig` / `utf-16`,
     then a `utf-8` attempt, otherwise a `cp1251` fallback (the de-facto
     codepage of Ukrainian CSVs from Windows);
   - `detect_delimiter()`: first `csv.Sniffer` on the first 20 lines; on
     failure a frequency + consistency heuristic (the same separator count
     on every line scores highest) over `, ; tab |`; falls back to comma.
2. **Header row detection.** `detect_header_row()` returns the 0-based
   index of the first non-empty row with ≥2 non-empty cells of which over
   50% are text: real sheets often start with a merged title or a blank
   band, and a single text cell is a title, not a header.
   `resolve_header_row()` takes the user's manual pick as a **1-based**
   number (as shown in the UI) and converts it to 0-based.
3. **Mapping columns onto entities.** `ENTITY_FIELDS` — six canonical
   fields: `item`, `quantity`, `status`, `assignee`, `due_date`, `amount`.
   `suggest_mapping()` proposes `{column -> entity}` for the mapping
   wizard with hybrid scoring over the `FIELD_SYNONYMS` dictionary
   (EN + UA): exact match = 1.0, substring = 0.85, otherwise
   `difflib.SequenceMatcher().ratio()`; threshold `SUGGEST_THRESHOLD = 0.6`.
   Assignment is greedy one-to-one, highest score first — a column never
   takes an entity already claimed by a better match.
4. **Building rows.** `parse_sheet()` returns a `SheetParse` (columns,
   up to 10 preview rows, total count, header index). `build_rows()`
   applies the mapping to the whole sheet: every value goes through a
   `VALIDATORS` coercer (per entity) and returns `(value, error)`. A row
   is skipped only when `item` (the identity) failed to parse or the row
   is completely empty; errors are collected into `RowError`, nothing
   fails silently. `validate_mapping()` checks: mapping non-empty,
   columns exist, entities known and not duplicated.

Custom fields are validated by `coerce_custom_value(ftype, v, options)`
for types `text | number | date | select` — same `(value, error)`
convention, an empty value is always valid (None).

### `app/calc.py` — formulas with DFS cycle validation

A collection can define calculated columns, e.g.
`{"total": "=quantity*amount"}`. The restrictions are deliberately strict:
arithmetic only (`+ - * / ( )`), numbers and identifiers (entity fields +
other calc columns); no function calls, attributes or arbitrary names.

- `parse_formula_tokens()` — the tokenizer; any foreign character is
  rejected with `ValueError` (this is the guard in front of `eval`).
- `validate_formula()` — checked on save: an unknown identifier is an error.
- `evaluate_formula()` — substitutes the row's numbers; a `None` input
  propagates to a `None` result (not 0, not an error), division by zero
  also yields `None`.
- `evaluate_row()` — computes all calc columns of a row; they may
  reference each other.
- `detect_cycles()` — a three-color DFS (WHITE/GRAY/BLACK) finds cyclic
  dependencies (e.g. `a = b+1`, `b = a*2`) and returns the list of cycles;
  an empty list means the formula set is a valid DAG. Formulas with a
  cycle cannot be saved: the request is rejected on the endpoint with an
  error instead of yielding `None` on every row.

### `app/db.py::audit` — the audit_events pattern: EVERY change is logged

Every state change goes through `db.audit(conn, user, action, ...)` — an
INSERT into the `audit_events` table (ts, user, collection_id, row_id,
action, field, old_value, new_value). This rule has no exceptions:
collection creation (`collection.created`) and rows, field edits
(`row.edited` with `field`/`old_value`/`new_value`), deletions
(`row.deleted`, `rows.bulk_deleted`, `collection.deleted`), custom fields
(`field.created`, `field.deleted`), saved filters (`filter.saved`,
`filter.deleted`), users (`user.created`), templates and demo. If you add
a new endpoint that changes data, it **must** call `db.audit`; the log is
read via `GET /api/collections/{cid}/audit` (admin only).

### Roles and permissions: admin / worker

All API routes require a session Bearer token (`current_user_info`).
Roles are `admin` and `worker` (`db.ROLES`); the first user of the system
is created as admin (`ensure_admin`).

| Action | admin | worker |
|---|---|---|
| Login, read collections/rows, filtering, export | yes | yes |
| Row edits (single, bulk status) | yes | yes |
| Kanban, saved filters (own), custom values | yes | yes |
| Deleting own saved filters | yes | yes |
| File import, column mapping | yes | no (403) |
| Creating/deleting collections, from template, demo | yes | no (403) |
| Custom fields: create/delete | yes | no (403) |
| Formulas (calc columns) | yes | no (403) |
| User management, audit log, reminders run/flush | yes | no (403) |
| Deleting someone else's saved filter | yes | no (403) |

The key function is `require_admin()`: raises `HTTPException(403,
"Admin role required")`. The rule: anything that changes a collection's
structure or mutates data in bulk/irreversibly is admin-only; a worker
works with rows. One exception: a saved filter can be deleted by its
author or an admin.

### Custom fields: `custom_fields` + `extra_json`

Custom fields live in the `custom_fields` table (name, label, type,
options_json, position — unique per collection), while their values live
in `rows.extra_json` as a JSON dict `{name: value}`. The design is
deliberate: the columns of `rows` are fixed by the six entities, and
arbitrary user fields do not break the schema. Types: `text`, `number`,
`date`, `select` (with `options_json`). Deleting a field necessarily
triggers `drop_custom_field_values` — the values are wiped from
`extra_json` of every row of the collection. Row search includes
`extra_json` values (see `app/main.py`, the `search_blob` construction).

## Environment & tests

```bash
git clone https://github.com/<user>/sheetflow.git && cd sheetflow
python -m pip install -r requirements.txt
python -m pytest tests/ -v          # must be green before a PR
python -m uvicorn app.main:app --reload
```

See also [INSTALL.md](INSTALL.md).

Tests never touch real files or databases: `tests/conftest.py` provides

- `client` — a fresh SQLite DB in `tmp_path` per test (`SHEETFLOW_DB`
  via monkeypatch), admin `admin/admin123`, a logged-in `TestClient`
  with a Bearer token;
- `make_xlsx(rows, headers=None)` — an **on-the-fly xlsx fixture**: it
  builds an openpyxl workbook in memory (`io.BytesIO`) — no binary files
  in the repository; `sample_xlsx` — the standard set of 4 rows (valid,
  edge-case, broken), `imported_collection` — a collection already
  imported from that file.

Write new tests in the same style: API via `client`, pure functions
(`importer`, `calc`) directly, without HTTP.

## Adding a new entity field

Example: adding `priority`. It becomes a first-class field — a column in
the `rows` table, a participant of mapping and formulas. Step by step:

1. **`app/importer.py` → `ENTITY_FIELDS`**: add `"priority"` to the list
   of canonical fields.
2. **`app/importer.py` → `FIELD_SYNONYMS`**: add the `"priority"` key
   with a list of synonyms — **both EN and UA**; that is exactly how
   `suggest_mapping()` recognizes the user's columns, e.g.
   `["priority", "prio", "importance", "пріоритет", "важливість",
   "терміновість"]`. Take real variants from live spreadsheets; without
   UA synonyms the import wizard will not recognize Ukrainian columns.
3. **`app/importer.py` → coercer + `VALIDATORS`**: write
   `_coerce_priority(v) -> (value, error)` following the convention
   empty = None, broken = `(None, "message")`, and add it to
   `VALIDATORS`. An empty value is **always** valid: fields are optional
   per row.
4. **`app/db.py` → `SCHEMA`**: add the column to `CREATE TABLE rows`;
   for existing databases add an entry to `MIGRATIONS`
   (`"rows": {"priority": "ALTER TABLE rows ADD COLUMN priority ..."}`);
   `init_db()` applies it automatically.
5. **`app/main.py`**: add the field to SELECTs, row creation, editing,
   CSV/JSON export and the kanban view — navigate by `ENTITY_FIELDS`
   occurrences in the code.
6. **`app/static/i18n.js`**: the column header in both dictionaries
   (`ua` and `en`), e.g. `th_priority`.
7. **Tests**: `tests/test_importer.py` (coercer: valid/empty/broken),
   `tests/test_fuzzy_mapping.py` (UA and EN synonyms recognized),
   `tests/test_api.py` (the field flows through import → list → edit →
   export).
8. **README (both) + CHANGELOG** — update the list of entities.

## Adding a collection template

Templates live in `app/templates.py` in the `TEMPLATES` dict — classic
processes («Замовлення», «Клієнти», «Інвентар», «Задачі», «Підписки»)
created with one click, complete with sample rows.

1. Add a key to `TEMPLATES`:
   ```python
   "contracts": {
       "name": "Договори",                       # UI name
       "columns": ["Контрагент", "К-сть", ...],  # canonical columns
       "mapping": {"Контрагент": "item", ...},   # column -> ENTITY_FIELD
       "sample_rows": [ {...}, {...} ],          # 2 realistic rows
   },
   ```
2. Rules: `mapping` may use only known `ENTITY_FIELDS`; every column from
   `columns` is mapped; `sample_rows` use exactly the same keys as
   `columns`; values are realistic (ISO dates `YYYY-MM-DD`, numbers as
   numbers).
3. `POST /api/collections/from-template` (admin only) creates a
   collection from the template: columns, mapping and sample rows are
   written to the DB and the event is logged as `collection.created`.
4. **Tests**: `tests/test_templates.py` — invariants of every template
   (valid mapping, rows match the columns); add a case for your template.
5. If the template introduced new column names — add them as synonyms to
   `FIELD_SYNONYMS` (section above) so importing "the same" file is
   recognized automatically.

## Branches, commits, PRs

- **`main` is the stable branch**: green pytest, clean tree, every commit
  deployable. Do not push unproven work to `main` and do not rewrite
  published history without a need.
- Features go to a `feat/<name>` branch, fixes to `fix/<name>`, docs to
  `docs/<name>`; PRs target `main`.
- One commit = one logical change; the message is a short imperative in
  English (`Docs: expanded CONTRIBUTING (UA+EN)`,
  `feat: reminders outbox`, `fix: cp1251 csv encoding`).
- Every feature = a commit + pytest tests. A PR without tests is not
  merged.
- Before a PR: `python -m pytest tests/ -v` green, `git status` clean.

## Code style

- Python: stdlib where possible; no new dependencies without discussion.
  FastAPI + sqlite3 (no ORM).
- Every feature = one commit + pytest tests (`python -m pytest tests/ -v`).
- Frontend is vanilla JS with no build step in `app/static/`.

## i18n (UA + EN)

All UI localization lives in `app/static/i18n.js`: two dictionaries
`ua:` and `en:` with identical key sets; HTML markup is annotated with
`data-i18n="key"` (text) / `data-i18n-ph="key"` (placeholder), and the
`applyI18n()` function applies the strings. Language resolution:
`localStorage.getItem('lang')` (saved choice) beats `navigator.language`
(auto: `startsWith("uk")` → ua), then the default ua; the `#langSel`
switcher persists the choice via `setLang`.

Rules:

- New UI text goes **always** into both dictionaries — a key missing from
  one language breaks `test_dictionaries_have_ua_and_en`.
- **Never Russian.** This is the project's policy and it is automated:
  `test_no_russian_in_i18n_and_ui` greps `[ЫыЪъЭэЁё]` — Russian-specific
  letters (ы, ъ, э, ё, absent from the Ukrainian alphabet) — in
  `/static/i18n.js` and on the main page. Ukrainian `и`/`і`/`є`/`ї`/`ґ`
  are allowed; if your text contains ы/ъ/э/ё, it is Russian — rewrite it.
- Documents (`README.md`, `README.en.md`, this file) pass the same filter
  in `test_oss.py` / `test_readmes.py`.

## Security: never change

The current model (`app/db.py`) is simple and honest — do not "improve"
it without discussing in an issue:

- **Passwords are PBKDF2-HMAC-SHA256** with a random per-user salt and
  `PBKDF2_ITERATIONS = 200_000`. Storage format:
  `pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`. Do not lower the
  iteration count, do not switch to bare sha256/MD5/a constant salt;
  `verify_password()` compares hashes only via `hmac.compare_digest`
  (constant-time) — do not replace it with `==`. Legacy v0.3.0 hashes
  (bare sha256) are recognized by `is_legacy_hash()` and supported only
  for logging in existing users.
- **Sessions**: `SESSION_TTL_SECONDS = 24*3600` — a token lives 24 hours;
  expired sessions are purged on every token lookup
  (`get_user_by_token`). Do not extend the TTL "for convenience" and do
  not make tokens eternal; logout deletes the row from `sessions`.
- The first user (`admin/admin123`) is a demo fixture password; the README
  explicitly says "change the password". No other password appears in
  code/tests — `test_passwords_are_fixture_only` enforces that.
- `db.audit` logs **without** passwords and tokens; never put secrets
  into it.
- When adding an endpoint, consciously choose `current_user_info` or
  `require_admin` (see the matrix above); "forgot the check" is a
  vulnerability, not a nitpick.

## Privacy

Never include in issues/PRs: real business data, local disk paths, tokens,
passwords. Test passwords are fixture-only (`admin/admin123` in tests).

## Local setup

```bash
git clone https://github.com/<user>/sheetflow.git && cd sheetflow
python -m pip install -r requirements.txt
python -m pytest tests/ -v
python -m uvicorn app.main:app --reload
```

See also [INSTALL.md](INSTALL.md).
