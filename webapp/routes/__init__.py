"""Доменные регистраторы маршрутов, извлечённые из app.py.

Каждый модуль экспортирует ``register_<domain>_routes(app, ctx)`` —
имена обработчиков (Flask endpoint) сохраняются, поэтому все
``url_for()`` в шаблонах продолжают работать без изменений.

Модули:
- ``admin`` — админка и /api/admin/*
- ``analysis`` — анализ и ML
- ``auth_pages`` — /login, /logout, /force-password-change
- ``aviation`` — авиация
- ``chat`` — чат
- ``crypto`` — крипто
- ``intercepts`` — перехваты
- ``jobs`` — export-jobs и AI analyze
- ``misc`` — health, databases, targeting
- ``online_search`` — API поиска онлайн
- ``sessions`` — сеансы
- ``shell`` — главная, вкладки, set-position, pick-folder
- ``sync_api`` — /api/sync/push, pull, status
"""
