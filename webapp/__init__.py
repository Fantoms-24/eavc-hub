"""HTTP-слой Flask: маршруты, auth, security, хелперы ответа.

Границы
-------
- ``webapp.context.AppContext`` — единый DI для всех ``register_*_routes(app, ctx)``.
- ``webapp.routes.*`` — только HTTP: парсинг запроса, права, вызов application/lib.
- Бизнес-сценарии без Flask — в ``application/`` (см. ``application.intercepts``).
- ``create_app`` в ``app.py`` собирает runtime (кэши, job-очереди, sync proxy)
  и передаёт зависимости через ``AppContext``.
"""
