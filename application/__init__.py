"""Прикладной слой: сценарии (use cases), отделённые от Flask и HTTP.

Правило размещения новой бизнес-логики
--------------------------------------
1. HTTP / JSON / ``request`` / ``login_required`` → ``webapp/routes/<domain>.py``
2. Сценарий без Flask (валидация, сборка ответа, оркестрация lib/*) →
   ``application/<domain>/``
3. Чистый доступ к данным / инфраструктура → ``lib/`` (для SQLite — ``lib/db/``)

Эталон: ``application/intercepts/`` (export DOCX, каталоги, позывные, AI-вычитка).
Новые домены (analysis, sessions, aviation, …) добавляйте по тому же шаблону:
тонкий route-handler вызывает ``execute_*`` / ``build_*`` из application.
"""
