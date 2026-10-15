"""Невесомый DOM-оверлей с оценками колонок — Вопросы №43-В, №44.

Инжектируется блок с pointer-events: none поверх доски: метки оценок над
колонками (формат задаёт вызывающий: WIN +7 / DRAW 0 / LOSS -12) и подсветка
рекомендуемой колонки. Обновляется один раз за ход, нулевая нагрузка.
"""

from __future__ import annotations

OVERLAY_ID = "__c4_overlay__"

_INJECT_JS = r"""
(args) => {
  const {board_rect, labels, best_col} = args;
  let host = document.getElementById("__c4_overlay__");
  if (!host) {
    host = document.createElement("div");
    host.id = "__c4_overlay__";
    host.style.cssText =
      "position:fixed;z-index:2147483646;pointer-events:none;" +
      "font:600 13px/1.2 system-ui,sans-serif;";
    document.body.appendChild(host);
  }
  const b = board_rect;
  host.style.left = b.x + "px";
  host.style.top = b.y + "px";
  host.style.width = b.w + "px";
  host.style.height = b.h + "px";
  host.innerHTML = "";
  const n = labels.length;
  for (let i = 0; i < n; i++) {
    const lbl = document.createElement("div");
    lbl.textContent = labels[i].text;
    lbl.dataset.col = String(i);
    lbl.style.cssText =
      "position:absolute;top:-22px;transform:translateX(-50%);padding:2px 6px;" +
      "border-radius:6px;background:rgba(16,24,32,.85);color:#dfe8f2;" +
      "white-space:nowrap;";
    lbl.style.left = ((i + 0.5) * 100 / n) + "%";
    if (labels[i].best) {
      lbl.style.background = "#17B99A";
      lbl.style.color = "#0b1f1a";
      const frame = document.createElement("div");
      frame.style.cssText =
        "position:absolute;top:0;border:3px solid #17B99A;border-radius:10px;" +
        "box-sizing:border-box;height:100%;pointer-events:none;";
      frame.style.left = (i * 100 / n) + "%";
      frame.style.width = (100 / n) + "%";
      host.appendChild(frame);
    }
    host.appendChild(lbl);
  }
  return {shown: n, best: best_col};
}
"""

_CLEAR_JS = r"""
() => {
  const host = document.getElementById("__c4_overlay__");
  if (host) host.remove();
  return true;
}
"""

_PRESENT_JS = r"""
() => !!document.getElementById("__c4_overlay__")
"""


def label_text(score: int) -> str:
    """Формат метки по плану Q44: WIN +n / DRAW 0 / LOSS -n."""
    if score > 0:
        return f"WIN +{score}"
    if score < 0:
        return f"LOSS {score}"
    return "DRAW 0"


def inject(page, board_rect: dict, per_column_scores: list[int], best_col=None):
    """Показать оценки колонок поверх доски.

    per_column_scores — точные оценки ходящего для каждой колонки
    (например, из SolverEngine.best_column при игре с ядром).
    """
    labels = [
        {"text": label_text(s), "best": (best_col is not None and i == best_col)}
        for i, s in enumerate(per_column_scores)
    ]
    return page.evaluate(_INJECT_JS, {
        "board_rect": board_rect,
        "labels": labels,
        "best_col": best_col,
    })


def clear(page):
    return page.evaluate(_CLEAR_JS)


def is_present(page) -> bool:
    return bool(page.evaluate(_PRESENT_JS))
