"""Regression coverage for intensity queries after database module extraction."""
import sqlite3

import pytest

from web_portal.lib.db import init_db, init_seans_tables
from web_portal.lib.db.network_intensity import (
    get_network_intensity_clusters,
    get_network_intensity_clusters_dual,
    get_network_intensity_clusters_dual_daily,
)


@pytest.mark.parametrize("mode", ["single", "dual", "daily"])
def test_intensity_uses_separate_storage_and_counts_archive(mode):
    with sqlite3.connect(":memory:") as main, sqlite3.connect(":memory:") as seans:
        main.row_factory = seans.row_factory = sqlite3.Row
        init_db(main)
        init_seans_tables(seans)
        main.execute("INSERT INTO unit (frequency, group_, name) VALUES ('151.0000', 'G1', 'Unit A')")
        for table, rows in (
            ("seanses", [
                ('2026-06-02 10:00:00', 'A', 'pos1'),
                ('2026-06-02 10:00:00', 'B', 'pos1'),
                ('2026-06-02 11:00:00', 'C', 'pos2'),
            ]),
            ("seanses_archive", [
                ('2026-06-02 10:00:00', 'A', 'pos1'),
                ('2026-06-02 12:00:00', 'A', 'pos1'),
                ('2026-06-01 10:00:00', 'D', 'pos1'),
            ]),
        ):
            seans.executemany(
                f"INSERT INTO {table} (date_time, frequency, group_, id, client_name) VALUES (?, '151.0000', 'G1', ?, ?)",
                rows,
            )
        seans.commit()
        common = dict(seans_conn=seans, position_name='pos1')
        if mode == 'single':
            current = get_network_intensity_clusters(
                main, start_dt='2026-06-02 00:00:00', end_dt='2026-06-02 23:59:59', **common,
            )
        else:
            query = get_network_intensity_clusters_dual_daily if mode == 'daily' else get_network_intensity_clusters_dual
            current, previous = query(
                main, cur_start_dt='2026-06-02 00:00:00', cur_end_dt='2026-06-02 23:59:59',
                prev_start_dt='2026-06-01 00:00:00', prev_end_dt='2026-06-01 23:59:59', **common,
            )
            assert previous == [dict(unit_name='Unit A', sessions=1, correspondents=1)]
        assert current == [dict(unit_name='Unit A', sessions=2, correspondents=2)]
