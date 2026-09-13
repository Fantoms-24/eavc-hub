"""Преобразование координат СК-42 (Гаусса–Крюгера) ↔ WGS84 — как на карте портала."""

from __future__ import annotations

import math
import re
from typing import Any

DEG = math.pi / 180.0
WGS84_a = 6378137.0
WGS84_f = 1 / 298.257223563
WGS84_e2 = 2 * WGS84_f - WGS84_f * WGS84_f
KRAS_a = 6378245.0
KRAS_f = 1 / 298.3
KRAS_e2 = 2 * KRAS_f - KRAS_f * KRAS_f


def _wgs84_to_sk42(lat_wgs: float, lon_wgs: float, h: float = 0.0) -> tuple[float, float]:
    b = lat_wgs * DEG
    l = lon_wgs * DEG
    sin_b = math.sin(b)
    cos_b = math.cos(b)
    n = WGS84_a / math.sqrt(1 - WGS84_e2 * sin_b * sin_b)
    x = (n + h) * cos_b * math.cos(l)
    y = (n + h) * cos_b * math.sin(l)
    z = ((1 - WGS84_e2) * n + h) * sin_b
    r_y = (-0.35 / 3600) * DEG
    r_z = (-0.736 / 3600) * DEG
    sx = (x - r_z * y + r_y * z) - 25.0
    sy = (r_z * x + y) + 141.0
    sz = (-r_y * x + z) + 78.5
    rl = math.atan2(sy, sx)
    rb = math.atan(sz / math.hypot(sx, sy))
    m_eps = 1e-12
    while True:
        rb0 = rb
        nk = KRAS_a / math.sqrt(1 - KRAS_e2 * math.sin(rb0) * math.sin(rb0))
        rb = math.atan((sz + KRAS_e2 * nk * math.sin(rb0)) / math.hypot(sx, sy))
        if abs(rb - rb0) <= m_eps:
            break
    return (rb / DEG, rl / DEG)


def _sk42_to_gauss_kruger(b: float, l: float) -> tuple[float, float, int]:
    b_k = b
    l_k = l
    b_k_rad = b_k * DEG
    n = int(math.floor((6 + l_k) / 6))
    ll = (l_k - (3 + 6 * (n - 1))) * DEG
    sin_bk = math.sin(b_k_rad)
    sin_bk2 = sin_bk * sin_bk
    sin_bk4 = sin_bk2 * sin_bk2
    sin_bk6 = sin_bk4 * sin_bk2
    l2 = ll * ll
    sx = (
        6367558.4968 * b_k_rad
        - math.sin(2 * b_k_rad)
        * (
            16002.8900
            + 66.9607 * sin_bk2
            + 0.3515 * sin_bk4
            - l2
            * (
                1594561.25
                + 5336.535 * sin_bk2
                + 26.79 * sin_bk4
                + 0.149 * sin_bk6
                + l2
                * (
                    672483.4
                    - 811219.9 * sin_bk2
                    + 5420.0 * sin_bk4
                    - 10.6 * sin_bk6
                    + l2
                    * (
                        278194.0
                        - 830174.0 * sin_bk2
                        + 572434.0 * sin_bk4
                        - 16010.0 * sin_bk6
                        + l2
                        * (
                            109500.0
                            - 574700.0 * sin_bk2
                            + 863700.0 * sin_bk4
                            - 398600.0 * sin_bk6
                        )
                    )
                )
            )
        )
    )
    sy = (5 + 10 * n) * 1e5 + ll * math.cos(b_k_rad) * (
        6378245.0
        + 21346.1415 * sin_bk2
        + 107.159 * sin_bk4
        + 0.5977 * sin_bk6
        + l2
        * (
            1070204.16
            - 2136826.66 * sin_bk2
            + 17.98 * sin_bk4
            - 11.99 * sin_bk6
            + l2
            * (
                270806.0
                - 1523417.0 * sin_bk2
                + 1327645.0 * sin_bk4
                - 21701.0 * sin_bk6
                + l2 * (79690.0 - 866190.0 * sin_bk2 + 1730360.0 * sin_bk4 - 945460.0 * sin_bk6)
            )
        )
    )
    return sx, sy, n


def wgs84_to_sk42_xy(lat_wgs: float, lon_wgs: float) -> tuple[float, float, int]:
    b, l = _wgs84_to_sk42(lat_wgs, lon_wgs)
    x, y, zone = _sk42_to_gauss_kruger(b, l)
    return x, y, zone


def sk42_xy_to_wgs84(x: float, y: float, zone: int | None = None) -> tuple[float, float]:
    n = max(1, min(60, int(zone or 21)))
    lat = 50.0
    lon = 6 * n - 3
    for _ in range(30):
        gk_x, gk_y, _ = wgs84_to_sk42_xy(lat, lon)
        d_x = x - gk_x
        d_y = y - gk_y
        if abs(d_x) < 0.1 and abs(d_y) < 0.1:
            break
        cos_lat = math.cos(lat * DEG)
        if cos_lat < 0.01:
            cos_lat = 0.01
        lat += d_x / 111320.0
        lon += d_y / (111320.0 * cos_lat)
    return lat, lon


def parse_sk42_pair_from_text(text: str) -> tuple[float, float] | None:
    raw = str(text or "")
    m = re.search(r"(\d{6,8})\s*[,;\s]\s*(\d{6,8})", raw)
    if not m:
        return None
    try:
        x = float(m.group(1))
        y = float(m.group(2))
    except ValueError:
        return None
    if x <= 0 or y <= 0:
        return None
    return x, y


def sk42_zone_from_y(y: float) -> int:
    """Зона Гаусса–Крюгера по полному Y (например 7364147 → зона 7)."""
    try:
        yy = float(y)
    except (TypeError, ValueError):
        return 21
    if yy >= 1_000_000:
        return max(1, min(60, int(yy // 1_000_000)))
    return 21


def coords_from_operating_area(text: str, zone: int | None = None) -> dict[str, Any]:
    pair = parse_sk42_pair_from_text(text)
    if not pair:
        return {"sk42_x": None, "sk42_y": None, "lat": None, "lon": None}
    x, y = pair
    z = int(zone) if zone is not None else sk42_zone_from_y(y)
    lat, lon = sk42_xy_to_wgs84(x, y, z)
    return {"sk42_x": x, "sk42_y": y, "lat": lat, "lon": lon, "sk42_zone": z}
