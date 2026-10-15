"""Невесомый DOM-оверлей с оценками колонок — Вопросы №43-В, №44.

Инжектируется блок с pointer-events: none поверх доски: метки оценок над
колонками (формат задаёт вызывающий: WIN +7 / DRAW 0 / LOSS -12) и подсветка
рекомендуемой колонки. Обновляется один раз за ход, нулевая нагрузка.

Позиционирование: `position: absolute` в координатах ДОКУМЕНТА + живая
привязка к элементу доски (ResizeObserver доски, MutationObserver body,
scroll/resize) — при сдвигах вёрстки (реклама, панели), скролле и смене
размеров оверлей едет вместе с доской и не «прыгает» (правка после
наблюдения пользователя 16.10.2026).
"""

from __future__ import annotations

INJECT_JS = r"""
(args) => {
  const {board_rect, labels, best_col} = args;
  const ID = "__c4_overlay__";
  let host = document.getElementById(ID);
  if (!host) {
    host = document.createElement("div");
    host.id = ID;
    host.style.cssText =
      "position:absolute;z-index:2147483646;pointer-events:none;" +
      "font:600 13px/1.2 system-ui,sans-serif;";
    document.body.appendChild(host);
  }
  const anchor = document.querySelector(".grid");

  const place = () => {
    const h = document.getElementById(ID);
    if (!h) return;
    const sx = window.scrollX || 0, sy = window.scrollY || 0;
    if (anchor) {
      const r = anchor.getBoundingClientRect();
      h.style.left = (r.x + sx) + "px";
      h.style.top = (r.y + sy) + "px";
      h.style.width = r.width + "px";
      h.style.height = r.height + "px";
    } else {
      h.style.left = (board_rect.x + sx) + "px";
      h.style.top = (board_rect.y + sy) + "px";
      h.style.width = board_rect.w + "px";
      h.style.height = board_rect.h + "px";
    }
  };

  if (!window.__c4_ov_obs) {
    const re = () => {
      if (window.__c4_raf) return;
      window.__c4_raf = requestAnimationFrame(() => {
        window.__c4_raf = 0;
        if (window.__c4_place) window.__c4_place();
      });
    };
    const obs = [];
    try {
      const ro = new ResizeObserver(re);
      if (anchor) ro.observe(anchor);
      obs.push(ro);
    } catch (e) {}
    try {
      const mo = new MutationObserver(re);
      mo.observe(document.body, {childList: true, subtree: true});
      obs.push(mo);
    } catch (e) {}
    window.addEventListener("scroll", re, {passive: true});
    window.addEventListener("resize", re);
    window.__c4_ov_obs = obs;
    window.__c4_ov_re = re;
  }
  window.__c4_place = place;
  place();
  // страховочный опрос: наблюдатели иногда не ловят возврат вёрстки назад —
  // один getBoundingClientRect каждые 300 мс решает это надёжно и бесплатно
  if (!window.__c4_ov_timer) {
    window.__c4_ov_timer = setInterval(() => {
      const h = document.getElementById(ID);
      if (!h) { clearInterval(window.__c4_ov_timer); window.__c4_ov_timer = null; return; }
      if (window.__c4_place) window.__c4_place();
    }, 300);
  }

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

CLEAR_JS = r"""
() => {
  const host = document.getElementById("__c4_overlay__");
  if (host) host.remove();
  const obs = window.__c4_ov_obs || [];
  for (const o of obs) { try { o.disconnect(); } catch (e) {} }
  if (window.__c4_ov_re) {
    try { window.removeEventListener("scroll", window.__c4_ov_re); } catch (e) {}
    try { window.removeEventListener("resize", window.__c4_ov_re); } catch (e) {}
  }
  window.__c4_ov_obs = null;
  window.__c4_ov_re = null;
  window.__c4_place = null;
  if (window.__c4_ov_timer) {
    clearInterval(window.__c4_ov_timer);
    window.__c4_ov_timer = null;
  }
  return true;
}
"""

_PRESENT_JS = r"""
() => !!document.getElementById("__c4_overlay__")
"""


def label_text(score) -> str:
    """Метка колонки: int -> WIN +n / DRAW 0 / LOSS -n; str -> как есть; None -> '?'."""
    if score is None:
        return "?"
    if isinstance(score, str):
        return score
    if score > 0:
        return f"WIN +{score}"
    if score < 0:
        return f"LOSS {score}"
    return "DRAW 0"


def inject(page, board_rect: dict, per_column_scores: list, best_col=None):
    """Показать оценки колонок поверх доски.

    per_column_scores — по элементу на колонку: int (точная оценка),
    str (готовая метка, напр. 'BLOCK') или None (неизвестно -> '?').
    """
    labels = [
        {"text": label_text(s), "best": (best_col is not None and i == best_col)}
        for i, s in enumerate(per_column_scores)
    ]
    return page.evaluate(INJECT_JS, {
        "board_rect": board_rect,
        "labels": labels,
        "best_col": best_col,
    })


def clear(page):
    return page.evaluate(CLEAR_JS)


def is_present(page) -> bool:
    return bool(page.evaluate(_PRESENT_JS))
