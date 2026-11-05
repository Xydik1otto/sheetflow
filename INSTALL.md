# Встановлення SheetFlow — для не-програміста

SheetFlow — локальний вебзастосунок: все живе на вашому комп'ютері, дані не
залишають пристрій. Весь шлях — 5 хвилин.

---

## Windows

### Крок 1. Python
1. Відкрийте https://www.python.org/downloads/ і поставте Python 3.10 або новіший.
2. **Важно:** на першому екрані інсталятора поставте галочку **«Add python.exe to PATH»**.

### Крок 2. Запуск
1. Розпакуйте папку проєкту (або `git clone`) куди завгодно, напр. `C:\SheetFlow`.
2. Двічі клацніть **`start.bat`** — він сам поставить залежності і запустить сервер.
3. Відкрийте в браузері **http://127.0.0.1:8000**.

Перший вхід: **admin / admin123** — і одразу змініть пароль (див. нижче).
Перший запуск — натисніть «Новий тут? завантажити демо-колекцію», щоб
подивитися, як усе працює, або одразу імпортуйте свій `.xlsx`.

### Автозапуск (якщо сервер потрібен постійно)
1. Натисніть `Win + R`, введіть `shell:startup`, Enter.
2. Створіть у папці ярлик на `start.bat` (права кнопка → «Створити ярлик» → перемістіть).
3. Тепер SheetFlow стартує разом із Windows. Щоб прибрати — видаліть ярлик.

### Зміна пароля адміна
Пароль зберігається хешем у базі `sheetflow.db`. Найпростіше: увійдіть під
`admin/admin123`, створіть нового користувача з роллю `admin` з вашим паролем
(кнопка «Користувачі» в UI / `POST /api/users`), увійдіть під ним і видаліть
старого `admin`.

---

## Linux (та macOS)

### Швидкий запуск
```bash
git clone https://github.com/<user>/sheetflow.git && cd sheetflow
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Автозапуск через systemd (user unit)
Створіть файл `~/.config/systemd/user/sheetflow.service`:

```ini
[Unit]
Description=SheetFlow (local web app)
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/sheetflow
ExecStart=%h/sheetflow/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=default.target
```

Потім:

```bash
systemctl --user daemon-reload
systemctl --user enable --now sheetflow
journalctl --user -u sheetflow -f   # подивитися логи
```

Щоб сервіс працював і коли ви не в системі: `sudo loginctl enable-linger $USER`.

---

## Оновлення

```bash
cd sheetflow
git pull            # або розпакуйте нову версію поверх
pip install -r requirements.txt
```

Схема бази оновлюється автоматично при старті (міграції додають колонки,
дані не втрачаються). Перед великими оновленнями зробіть експорт усіх даних
кнопкою «Експорт JSON» в UI або просто скопіюйте файл `sheetflow.db`.

## Де живуть дані

| Що | Де |
|---|---|
| База даних | `sheetflow.db` поруч із проєктом (змінна `SHEETFLOW_DB`) |
| Експорт | кнопки «Експорт CSV» / «Експорт JSON» у UI |

## Типові проблеми

- **«python не є внутрішньою або зовнішньою командою»** — перевстановіть Python
  з галочкою «Add to PATH», або запустіть `start.bat` ще раз.
- **Порт 8000 зайнятий** — запустіть на іншому:
  `python -m uvicorn app.main:app --port 8001`.
- **Забули пароль** — зупиніть сервер, перейменуйте `sheetflow.db`, запустіть
  знову (створиться свіжий admin/admin123), потім перенесіть дані експортом.
