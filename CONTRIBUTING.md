# Contributing to SheetFlow / Як долучитися до SheetFlow

Дякуємо за інтерес до проєкту! Будь-який внесок вітається: баг-репорти,
ідеї, переклади, код.

Thank you for your interest in SheetFlow! Contributions of every kind are
welcome: bug reports, ideas, translations, code.

## Як повідомити про проблему / How to report a bug

1. Перевірте, чи проблема вже є серед [issues](../../issues).
2. Створіть новий issue за шаблоном **Bug report** — шаблон англійською
   та українською, пишіть будь-якою з цих мов.
3. Додайте: версію Python, ОС, кроки відтворення, очікуваний/фактичний результат.

1. Check whether the problem already exists in [issues](../../issues).
2. Open a new issue using the **Bug report** template — it is in English and
   Ukrainian; write in either language.
3. Include: Python version, OS, steps to reproduce, expected/actual result.

## Пропозиції функцій / Feature requests

Використовуйте шаблон **Feature request**: описуємо проблему, яку фіча розв'язує,
а не лише «хочу кнопку». / Use the **Feature request** template: describe the
problem the feature solves, not just "I want a button".

## Стиль коду / Code style

- Python: стандартна бібліотека там, де можливо; без нових залежностей без
  обговорення. FastAPI + sqlite3 (без ORM).
- Кожна фіча = окремий commit + pytest-тести (`python -m pytest tests/ -v`).
- Фронтенд — vanilla JS без build-кроку в `app/static/`.

- Python: stdlib where possible; no new dependencies without discussion.
  FastAPI + sqlite3 (no ORM).
- Every feature = one commit + pytest tests (`python -m pytest tests/ -v`).
- Frontend is vanilla JS with no build step in `app/static/`.

## Мови / Languages

Інтерфейс і документація — **українською та англійською**. Російську
локалізацію не додаємо — це свідоме рішення власника проєкту; такі PR
закриваються без обговорення.

The UI and docs are **Ukrainian and English**. Russian localization is not
accepted — a deliberate decision of the project owner; such PRs are closed
without discussion.

## Приватність / Privacy

Ніколи не додавайте до issue/PR: реальні бізнес-дані, шляхи з вашого диска,
токени, паролі. Тестові паролі — тільки fixture-ові (`admin/admin123` у тестах).

Never include in issues/PRs: real business data, local disk paths, tokens,
passwords. Test passwords are fixture-only (`admin/admin123` in tests).

## Локальний запуск / Local setup

```bash
git clone https://github.com/<user>/sheetflow.git && cd sheetflow
python -m pip install -r requirements.txt
python -m pytest tests/ -v
python -m uvicorn app.main:app --reload
```

Див. також [INSTALL.md](INSTALL.md). / See also [INSTALL.md](INSTALL.md).
