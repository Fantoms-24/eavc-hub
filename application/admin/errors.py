"""Ошибки use case админки → HTTP-ответ (тонкий слой без Flask)."""


class AdminUseCaseHTTP(Exception):
    """Слой приложения сообщает код и тело как у прежних jsonify(...) в маршруте."""

    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = int(status_code)
        self.payload = dict(payload)
        super().__init__(str(payload.get("error") or payload))
