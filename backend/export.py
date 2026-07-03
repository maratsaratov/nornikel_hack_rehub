"""Экспорт ранжированных гипотез в Markdown и CSV.

Покрывает требование задачи «выдавать результат во всех необходимых форматах»
и «экспорт итогов в удобный формат» (JSON отдаётся напрямую из app.py).
"""
import csv
import io


def _scores(h):
    return h.get("effective_scores") or h.get("scores") or {}


def to_markdown(project, hyps, weights):
    L = []
    L.append(f"# Гипотезы НИОКР — {project.get('title', '')}\n")
    L.append(f"**Цель (KPI):** {project.get('kpi_target', '')}  ")
    if project.get("kpi_metric"):
        L.append(f"**Метрика:** {project['kpi_metric']} ({project.get('kpi_direction')})  ")
    if project.get("domain"):
        L.append(f"**Область:** {project['domain']}  ")
    w = weights or {}
    L.append(
        f"\n**Веса ранжирования:** новизна {w.get('novelty')} · ценность {w.get('value')} · "
        f"реализуемость {w.get('feasibility')} · риск {w.get('risk')}\n"
    )
    L.append(f"Всего гипотез: {len(hyps)}\n\n---\n")

    for i, h in enumerate(hyps, 1):
        s = _scores(h)
        L.append(f"## {i}. {h.get('statement', '')}\n")
        L.append(f"**Ранг (composite):** {h.get('composite')} · **Статус:** {h.get('status')}\n")
        if h.get("goal_link"):
            L.append(f"**Связь с целью:** {h['goal_link']}\n")
        if h.get("mechanism"):
            L.append(f"**Механизм влияния:** {h['mechanism']}\n")
        if h.get("rationale"):
            L.append(f"**Обоснование:** {h['rationale']}\n")
        if h.get("validation"):
            L.append(f"**План проверки:** {h['validation']}\n")
        L.append(
            f"**Оценки (0–100):** новизна {s.get('novelty')}, ценность {s.get('value')}, "
            f"реализуемость {s.get('feasibility')}, риск {s.get('risk')}\n"
        )
        ev = h.get("evidence") or []
        if ev:
            L.append("**Источники:**")
            for e in ev:
                bits = [e.get("title")]
                if e.get("snippet"):
                    bits.append(f"«{e['snippet']}»")
                L.append(f"- {' — '.join(b for b in bits if b)}")
            L.append("")
        if h.get("tags"):
            L.append(f"*Теги:* {', '.join(h['tags'])}\n")
        if h.get("expert_notes"):
            L.append(f"> Заметка эксперта: {h['expert_notes']}\n")
        L.append("---\n")
    return "\n".join(L)


def to_csv(hyps):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "rank_composite", "status", "statement", "goal_link", "mechanism", "validation",
        "novelty", "value", "feasibility", "risk", "tags", "sources",
    ])
    for h in hyps:
        s = _scores(h)
        srcs = "; ".join(filter(None, [e.get("title") for e in (h.get("evidence") or [])]))
        w.writerow([
            h.get("composite"), h.get("status"), h.get("statement"), h.get("goal_link") or "",
            h.get("mechanism") or "", h.get("validation") or "",
            s.get("novelty"), s.get("value"), s.get("feasibility"), s.get("risk"),
            ", ".join(h.get("tags") or []), srcs,
        ])
    return "﻿" + buf.getvalue()  # BOM — чтобы Excel корректно открыл кириллицу
