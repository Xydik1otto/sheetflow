# SheetFlow — Excel → App migrator for small businesses

![tests](https://img.shields.io/badge/tests-168%20passing-brightgreen)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![version](https://img.shields.io/badge/version-1.0.0-orange)

> Українська версія: [README.md](README.md)

## Why this exists

Small businesses have lived in Excel for decades — and keep living in it,
because no off-the-shelf tool replicates *their* process:

- **96%** of FP&A professionals still work in Excel (AFP 2025).
- **72%** of SMEs keep their finances in spreadsheets.
- Typical SMB complaints: *"our process is too custom, no tool fits"*, no audit
  trail ("who changed the price?!"), files named `final_v7_latest_final.xlsx`,
  and the panic when the ops lead is on vacation and nobody knows how "that
  same" file is structured.

SheetFlow exists to take those pains away: instead of forcing people to change
their process, it imports THEIR process — and immediately gives them what
Excel lacks: type validation, multi-user collaboration with roles, and an
indestructible "who/when/what changed" log.

## The idea

**Don't force a process change — import the existing one.**

1. Upload your usual `.xlsx` (or `.csv`).
2. The import wizard **suggests the column mapping for you** (fuzzy matching on
   column names, Ukrainian/English); you just confirm or fix it. The header row
   is auto-detected or picked manually. Multi-sheet workbooks get a sheet selector.
3. SheetFlow creates a validated collection and brings order to the chaos.
4. From there: a table with filters, **inline editing of every field**,
   **custom fields** (text/number/date/select) for your very custom process,
   **formulas** between fields (`=quantity*amount`, cycles rejected),
   **audit log** (who/when/what changed), overdue deadlines highlighted in red,
   kanban view, and CSV/JSON export back to the ordinary world.

## Features (v1.0.0)

- Import of `.xlsx` **and `.csv`** with **fuzzy auto-mapping**, **auto-detected
  header row** and a **sheet selector** for multi-sheet workbooks; CSV files get
  automatic delimiter (`,` `;` tab `|`) and encoding detection (UTF-8/UTF-16 BOM → CP1251).
- **Custom fields**: user-defined columns per collection — `text`, `number`,
  `date`, `select` (with option lists). Editable inline and in bulk actions.
- **Calculated columns**: formulas like `=quantity*amount` over entity and
  custom fields; formula cycles are rejected at write time.
- **Kanban board** by status with drag & drop (table/kanban toggle).
- **Saved filters** (named views) — quick access to your favorite data slices.
- **Bulk actions**: checkboxes → mass status change or delete, one audit event
  per row.
- **Five one-click collection templates**: orders, clients, inventory, tasks,
  subscriptions — each with sample rows and a ready mapping.
- **First-run demo**: an opt-in "load a demo collection" button that shows
  custom fields and formulas in action.
- **Reminders on due dates**: email outbox queue (`/api/reminders/*`),
  idempotent runs, real SMTP delivery when configured.
- **Data safety**: one-click JSON export of everything, CSV per collection,
  guarded (typed-confirmation) collection deletion.
- **Security**: PBKDF2 passwords (salt + 200k iterations), 24h session TTL,
  logout, `admin`/`worker` roles.
- **i18n**: Ukrainian/English switcher in the UI, browser-language
  auto-detection, choice persisted. (No Russian localization, by design.)
- **Accessibility**: aria-labels on interactive elements, live status regions,
  visible keyboard focus, Enter-key navigation in the key flows.

The first user of the system automatically becomes the admin.

## Quick start

```bash
git clone https://github.com/<user>/sheetflow.git && cd sheetflow
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload    # http://127.0.0.1:8000
```

Or install as a package:

```bash
pip install -e .
sheetflow    # boots the server on http://127.0.0.1:8000
```

**Demo access:** `admin / admin123` (first user = admin; change the password
before production). Step-by-step installation for non-programmers:
[INSTALL.md](INSTALL.md).

## Tests

```bash
python -m pytest tests/ -v
```

CI: GitHub Actions runs the tests on Python 3.12 and 3.13 on every push
(`.github/workflows/tests.yml`).

## Stack

Python 3.10+, FastAPI, SQLite (stdlib `sqlite3`, no ORM), openpyxl,
HTML + vanilla JS with no build step.

## Configuration

| Variable | Description | Default |
|---|---|---|
| `SHEETFLOW_DB` | path to the SQLite file | `sheetflow.db` next to the project |
| `SHEETFLOW_SMTP_*` | SMTP settings for reminder delivery | unset (outbox-only mode) |

## Roadmap

- [x] Overdue deadline notifications (email outbox)
- [x] Roles & multi-user (admin / worker)
- [x] CSV import + Kanban + saved filters + bulk actions (v0.4.0)
- [x] Custom fields, formulas with cycle validation, 5 templates,
      multi-sheet import, i18n, demo collection (v1.0.0)
- [ ] Re-import (upsert by key)
- [ ] Telegram notifications
- [ ] Google Sheets / 1C integrations

## Smoke test

```bash
bash scripts/smoke.sh   # boots a server on a random port and probes the endpoints
```

## Contributing

PRs and issues are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md),
security — [SECURITY.md](SECURITY.md). UI languages: Ukrainian and English
only (a deliberate project decision).

Recommended GitHub topics for the repository:
`smb`, `excel`, `no-code`, `fastapi`, `sqlite`, `small-business`.

## License

[MIT](LICENSE)
