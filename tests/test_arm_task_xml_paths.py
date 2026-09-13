"""Безопасное разрешение пути к ArmTask XML."""

from __future__ import annotations

import tempfile
from pathlib import Path

from web_portal.lib.arm_task_xml import resolve_arm_task_xml_path


def test_resolve_arm_task_xml_path_file() -> None:
    td = Path(tempfile.mkdtemp())
    xml = td / "Tempfinder_test.xml"
    xml.write_text('<?xml version="1.0"?><ArmTask></ArmTask>', encoding="utf-8")
    path, err, picked = resolve_arm_task_xml_path(str(xml))
    assert err == ""
    assert picked is False
    assert path is not None
    assert path.name == "Tempfinder_test.xml"


def test_resolve_arm_task_xml_path_dir_picks_newest() -> None:
    td = Path(tempfile.mkdtemp())
    old = td / "Tempfinder_old.xml"
    new = td / "Tempfinder_new.xml"
    old.write_text('<?xml version="1.0"?><ArmTask></ArmTask>', encoding="utf-8")
    new.write_text('<?xml version="1.0"?><ArmTask></ArmTask>', encoding="utf-8")
    path, err, picked = resolve_arm_task_xml_path(str(td))
    assert err == ""
    assert picked is True
    assert path is not None
    assert path.name in {old.name, new.name}
