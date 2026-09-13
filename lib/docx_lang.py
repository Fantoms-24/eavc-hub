from __future__ import annotations
import logging

_log = logging.getLogger("web_portal.lib.docx_lang")

try:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
except Exception:  # pragma: no cover
    OxmlElement = None  # type: ignore
    qn = None  # type: ignore


def _set_lang_on_rpr(rpr, *, lang_tag: str) -> None:
    """
    Добавляет/обновляет w:lang в rPr.
    lang_tag обычно "ru-RU".
    """
    if not rpr or not OxmlElement or not qn:
        return
    try:
        # python-docx: rPr — это oxml element; find работает по QName
        lang_el = rpr.find(qn("w:lang"))
        if lang_el is None:
            lang_el = OxmlElement("w:lang")
            rpr.append(lang_el)
        # val — основной язык для spellcheck
        lang_el.set(qn("w:val"), str(lang_tag))
        # на всякий случай, чтобы разные движки не игнорировали
        lang_el.set(qn("w:eastAsia"), str(lang_tag))
        lang_el.set(qn("w:bidi"), str(lang_tag))
    except Exception:
        return


def set_doc_language_ru(doc) -> None:
    """
    Ставит русский язык (ru-RU) как дефолтный для документа/стилей.
    Это помогает OnlyOffice/Word корректно включать русскую проверку.
    """
    if not doc:
        return
    try:
        styles = getattr(doc, "styles", None)
        if styles:
            try:
                normal = styles["Normal"]
                rpr = normal.element.get_or_add_rPr()
                _set_lang_on_rpr(rpr, lang_tag="ru-RU")
            except Exception:
                _log.debug("set_doc_language_ru: suppressed error", exc_info=True)
            # Table Grid часто используется — пробуем тоже
            try:
                tg = styles["Table Grid"]
                rpr = tg.element.get_or_add_rPr()
                _set_lang_on_rpr(rpr, lang_tag="ru-RU")
            except Exception:
                _log.debug("set_doc_language_ru: suppressed error", exc_info=True)
    except Exception:
        _log.debug("set_doc_language_ru: suppressed error", exc_info=True)


def set_run_language_ru(run) -> None:
    """
    Ставит русский язык на конкретный run (надежнее для таблиц).
    """
    if not run:
        return
    try:
        rpr = run._element.get_or_add_rPr()  # type: ignore[attr-defined]
        _set_lang_on_rpr(rpr, lang_tag="ru-RU")
    except Exception:
        return


