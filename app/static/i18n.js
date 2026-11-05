/* SheetFlow i18n: UA/EN dictionaries (no Russian — political decision of the owner). */
const I18N = {
  ua: {
    app_tagline: "Імпортуйте свій процес, а не міняйте його",
    login_h: "Вхід", ph_user: "Логін (admin)", ph_pass: "Пароль", login_btn: "Увійти",
    login_hint: "Перший користувач — admin/admin123 (змініть пароль у БД)",
    step1_h: "1. Завантажте ваш .xlsx або .csv", upload_btn: "Аналізувати",
    step2_h: "2. Назвіть колекцію та змапте колонки",
    sheet_label: "Аркуш:", header_row_label: "Рядок-шапка:",
    ph_coll_name: "Назва, напр. Замовлення",
    col_file: "Колонка з файлу", col_sample: "Приклад", col_entity: "Сутність",
    create_coll_btn: "Створити колекцію",
    collections_h: "Колекції", tpl_btn: "Створити з шаблоном",
    tpl_or: "або імпортуйте файл нижче ↓",
    th_id: "#", th_name: "Назва", th_file: "Файл", th_rows: "Рядків", th_created: "Створено",
    open_btn: "Відкрити",
    th_item: "Товар", th_qty: "К-сть", th_status: "Статус", th_assignee: "Виконавець",
    th_due: "Дедлайн", th_amount: "Сума",
    f_status: "— статус —", f_overdue: "— дедлайн —", f_only_overdue: "Тільки прострочені",
    ph_search: "Пошук...", filter_btn: "Фільтрувати", export_btn: "Експорт CSV",
    f_saved: "— збережені фільтри —", save_filter_btn: "💾 Зберегти фільтр",
    del_filter_btn: "✖ Видалити фільтр", view_table: "Таблиця", view_kanban: "Канбан",
    selected_n: "Вибрано:", f_new_status: "— новий статус —",
    bulk_status_btn: "Змінити статус", bulk_delete_btn: "Видалити вибрані",
    custom_fields_h: "Користувацькі поля", fields_none: "Ще немає користувацьких полів",
    add_field_btn: "Додати поле",
    ph_field_name: "ім'я латиницею, напр. priority", ph_field_label: "Назва в таблиці",
    ph_field_options: "варіанти через кому (для select)",
    del_field_confirm: "Видалити поле разом з його значеннями у всіх рядках?",
    audit_h: "Журнал змін (audit)",
    opt_status: "— статус —", opt_new_status: "— новий статус —",
    overdue_badge: "прострочено", kanban_no_name: "(без назви)",
    prompt_filter_name: "Назва фільтра:",
    alert_pick_filter: "Виберіть фільтр зі списку", alert_export_error: "Помилка експорту",
    alert_pick_status: "Виберіть статус",
    confirm_delete_rows: "Видалити {n} рядків?",
    bulk_failed: "Не вдалося:", bulk_delete_failed: "Не видалено:",
    auto_header_row: "Авто (рядок {n})", header_row_n: "Рядок {n}",
    demo_btn: " завантажити демо-колекцію", demo_hint: "Новий тут?",
    export_json_btn: "⬇ Експорт JSON (усі дані)",
    del_coll_btn: "Видалити",
    confirm_delete_coll: "Видалити колекцію «{name}» разом з {n} рядками? Введіть назву колекції для підтвердження:",
    confirm_delete_coll_mismatch: "Назва не збігається — видалення скасовано.",
    reimport_btn: "↻ Повторний імпорт (upsert)",
    alert_pick_file: "Виберіть файл для повторного імпорту",
    reimport_result: "Повторний імпорт: +{ins} нових, {upd} оновлено, {skip} пропущено, помилок: {err}",
  },
  en: {
    app_tagline: "Import your process, don't change it",
    login_h: "Sign in", ph_user: "Username (admin)", ph_pass: "Password", login_btn: "Sign in",
    login_hint: "First user becomes admin — admin/admin123 (change the password)",
    step1_h: "1. Upload your .xlsx or .csv", upload_btn: "Analyze",
    step2_h: "2. Name the collection and map the columns",
    sheet_label: "Sheet:", header_row_label: "Header row:",
    ph_coll_name: "Name, e.g. Orders",
    col_file: "Column from file", col_sample: "Sample", col_entity: "Entity",
    create_coll_btn: "Create collection",
    collections_h: "Collections", tpl_btn: "Create from template",
    tpl_or: "or import a file below ↓",
    th_id: "#", th_name: "Name", th_file: "File", th_rows: "Rows", th_created: "Created",
    open_btn: "Open",
    th_item: "Item", th_qty: "Qty", th_status: "Status", th_assignee: "Assignee",
    th_due: "Due date", th_amount: "Amount",
    f_status: "— status —", f_overdue: "— due date —", f_only_overdue: "Overdue only",
    ph_search: "Search...", filter_btn: "Filter", export_btn: "Export CSV",
    f_saved: "— saved filters —", save_filter_btn: "💾 Save filter",
    del_filter_btn: "✖ Delete filter", view_table: "Table", view_kanban: "Kanban",
    selected_n: "Selected:", f_new_status: "— new status —",
    bulk_status_btn: "Change status", bulk_delete_btn: "Delete selected",
    custom_fields_h: "Custom fields", fields_none: "No custom fields yet",
    add_field_btn: "Add field",
    ph_field_name: "latin name, e.g. priority", ph_field_label: "Label in the table",
    ph_field_options: "comma-separated options (for select)",
    del_field_confirm: "Delete this field and its values in all rows?",
    audit_h: "Change log (audit)",
    opt_status: "— status —", opt_new_status: "— new status —",
    overdue_badge: "overdue", kanban_no_name: "(no name)",
    prompt_filter_name: "Filter name:",
    alert_pick_filter: "Pick a filter from the list", alert_export_error: "Export error",
    alert_pick_status: "Pick a status",
    confirm_delete_rows: "Delete {n} rows?",
    bulk_failed: "Failed:", bulk_delete_failed: "Not deleted:",
    auto_header_row: "Auto (row {n})", header_row_n: "Row {n}",
    demo_btn: " load a demo collection", demo_hint: "New here?",
    export_json_btn: "⬇ Export JSON (all data)",
    del_coll_btn: "Delete",
    confirm_delete_coll: "Delete collection \"{name}\" with {n} rows? Type the collection name to confirm:",
    confirm_delete_coll_mismatch: "Name does not match — deletion cancelled.",
    reimport_btn: "↻ Re-import (upsert)",
    alert_pick_file: "Pick a file to re-import",
    reimport_result: "Re-import: +{ins} inserted, {upd} updated, {skip} skipped, {err} errors",
  },
};

function detectLang() {
  const saved = localStorage.getItem("lang");
  if (saved === "ua" || saved === "en") return saved;
  const nav = (navigator.language || "").toLowerCase();
  return nav.startsWith("uk") ? "ua" : "en"; // auto-detect browser language
}

function t(key, vars) {
  let s = (I18N[window.__lang] || I18N.ua)[key] ?? (I18N.ua[key] ?? key);
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll("{" + k + "}", v);
  return s;
}

function applyI18n() {
  window.__lang = detectLang();
  document.documentElement.lang = window.__lang === "ua" ? "uk" : "en";
  const sel = document.getElementById("langSel");
  if (sel) sel.value = window.__lang;
  document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-ph]").forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
}
