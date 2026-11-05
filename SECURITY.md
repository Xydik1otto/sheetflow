# Security Policy / Політика безпеки

## Supported versions / Підтримувані версії

| Version | Supported |
|---|---|
| 1.0.x | ✅ |
| < 1.0 | ❌ (update / оновіться) |

## Reporting a vulnerability / Як повідомити про вразливість

**EN:** Do **not** open a public issue for security vulnerabilities.
Use GitHub **Private vulnerability reporting** (Security → Report a
vulnerability) or contact the maintainer directly. Include a description,
reproduction steps and affected version. You will get a response within
7 days; fixes are released as patch versions.

**UA:** Не створюйте публічний issue для вразливостей. Скористайтеся
**Приватним повідомленням про вразливість** на GitHub (Security → Report a
vulnerability) або напишіть maintainer'у напряму. Опишіть проблему, кроки
відтворення та версію. Відповідь — протягом 7 днів; виправлення виходять
патч-версіями.

## Scope / Що вважаємо вразливістю

- Authentication/session bypass, privilege escalation (worker → admin).
- SQL injection, XSS через імпортовані дані, path traversal.
- Leakage of user data through API responses.

## Out of scope / Поза межами

- The app is designed for **local/trusted-network** deployment; reports about
  exposing it directly to the internet without a reverse proxy/TLS are
  configuration advice, not vulnerabilities (still, write us — we'll improve docs).
- Самостійний хостинг без HTTPS — питання конфігурації, а не вразливість.
