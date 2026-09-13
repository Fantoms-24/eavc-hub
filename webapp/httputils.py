"""Общие HTTP-хелперы, извлечены из app.py дословно."""

from __future__ import annotations

import hashlib
import json

from flask import Response, request


def json_etag_response(
    payload: dict, *, max_age: int = 15, status: int = 200
) -> Response:
    body = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")
    etag = '"' + hashlib.sha1(body).hexdigest() + '"'
    if request.headers.get("If-None-Match") == etag:
        resp = Response(status=304)
        resp.headers["ETag"] = etag
        resp.headers["Cache-Control"] = f"private, max-age={max(0, int(max_age))}"
        return resp
    resp = Response(body, status=status, mimetype="application/json; charset=utf-8")
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = f"private, max-age={max(0, int(max_age))}"
    return resp
