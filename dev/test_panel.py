#!/usr/bin/env python3
"""Playwright smoke for the lux_balance page inside the Fumiha Hub shell (L2)
+ screenshots (L3 base). Same pattern as FumihaHub dev/test_panel.py.

Covers:
  1. shell boots; luxbalance tab with provider badge, auto-selected
  2. page mounts: two zone cards render (calibrated + curveless)
  3. curve SVG polyline with fixture points; chips carry max/slope
  4. decision table rows
  5. target apply -> number/set_value call + ack toast
  6. calibrate -> confirm dialog -> lux_balance/calibrate with entity_id
  7. calibrating fixture -> progress note renders
  8. ?failapi=1 -> error card with retry
  9. ?badmodule=1 -> shell error card
 10. ?standalone=1 -> fallback mode boots from vendored kit/tokens
 11. screenshots light/dark x desktop/narrow -> dev/shots/

Usage: python dev/test_panel.py
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SHOTS = Path(__file__).resolve().parent / "shots"
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  ok  " if cond else "FAIL  ") + name + (f": {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(f"{name}: {detail}")


def start_server() -> tuple[ThreadingHTTPServer, int]:
    spec = importlib.util.spec_from_file_location(
        "lb_serve", Path(__file__).parent / "serve.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    server = ThreadingHTTPServer(("127.0.0.1", 0), mod.DevHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def main() -> int:
    from playwright.sync_api import sync_playwright

    server, port = start_server()
    base = f"http://127.0.0.1:{port}"
    SHOTS.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            run_checks(browser, base)
        finally:
            browser.close()
    server.shutdown()

    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        return 1
    print("\nall green")
    return 0


def page_dom(page, selector: str):
    """Query the page element's shadow DOM (one nesting level down)."""
    return page.evaluate(
        """([sel]) => {
          const find = () => {
            let p = document.getElementById('hub');
            if (!p || !p.shadowRoot) return null;
            for (const el of p.shadowRoot.querySelectorAll('*')) {
              if (el.shadowRoot && el.shadowRoot.querySelector(sel)) {
                return el.shadowRoot.querySelector(sel);
              }
            }
            return null;
          };
          const n = find();
          return n ? (n.dataset ? {found: true, text: (n.textContent||'').slice(0,80), count: 1} : {found: true}) : {found: false};
        }""",
        [selector],
    )


def wait_dom(page, selector: str, label: str, timeout_ms: int = 9000) -> None:
    page.wait_for_function(
        """(sel) => {
          const p = document.getElementById('hub');
          if (!p || !p.shadowRoot) return false;
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.shadowRoot && el.shadowRoot.querySelector(sel)) return true;
          }
          return false;
        }""",
        arg=selector,
        timeout=timeout_ms,
    )
    check(label, True)


def run_checks(browser, base: str) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # ---- 1+2: shell boot, tab, page mount ----------------------------------
    page.goto(base + "/")
    wait_dom(page, '[data-zone="e1"]', "page mounts: zone e1 card renders")
    wait_dom(page, '[data-zone="e2"]', "page mounts: zone e2 card renders")

    tabs = page.evaluate(
        """() => [...document.getElementById('hub').shadowRoot.querySelectorAll('.fx-tab')]
                 .map(t => ({badge: t.querySelector('.fx-badge').textContent, sel: t.getAttribute('aria-selected')}))"""
    )
    check("luxbalance tab present", len(tabs) == 1 and tabs[0]["badge"] == "luxbalance", str(tabs))
    check("tab auto-selected", tabs[0]["sel"] == "true", str(tabs))

    # ---- 3: curve ------------------------------------------------------------
    poly = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const svg = el.shadowRoot && el.shadowRoot.querySelector('svg[aria-label*="标定曲线"]');
            if (svg) {
              const line = svg.querySelector('polyline');
              return {points: line.getAttribute('points').trim().split(' ').length,
                      dots: svg.querySelectorAll('circle').length};
            }
          }
          return null;
        }"""
    )
    check("curve polyline has 6 fixture points", poly and poly["points"] == 6, str(poly))
    check("curve hover dots present", poly and poly["dots"] == 6, str(poly))

    chips = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const card = el.shadowRoot && el.shadowRoot.querySelector('[data-zone="e1"]');
            if (card) return card.textContent;
          }
          return '';
        }"""
    )
    check("curve chips carry max/slope", "最大增量 186.3 lx" in chips and "斜率 2.41" in chips, chips[:120])

    # ---- 4: decision table -----------------------------------------------------
    rows = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const card = el.shadowRoot && el.shadowRoot.querySelector('[data-zone="e1"]');
            if (card) return card.querySelectorAll('tbody tr').length;
          }
          return -1;
        }"""
    )
    check("decision table has 3 rows", rows == 3, str(rows))

    # ---- 5: target apply ---------------------------------------------------------
    page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const card = el.shadowRoot && el.shadowRoot.querySelector('[data-zone="e1"]');
            if (card) {
              const input = card.querySelector('input[type="number"]');
              input.value = '200';
              [...card.querySelectorAll('button')].find(b => b.textContent === '应用目标').click();
              return true;
            }
          }
          return false;
        }"""
    )
    page.wait_for_function(
        """() => (window.__serviceCalls || []).some(c => c.domain === 'number' && c.service === 'set_value' && c.data.value === 200)""",
        timeout=4000,
    )
    check("target apply calls number/set_value", True)
    page.wait_for_function(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.shadowRoot && el.shadowRoot.querySelector('.fx-toast')) return true;
          }
          return false;
        }""",
        timeout=4000,
    )
    check("ack toast appears", True)

    # ---- 6: calibrate flow --------------------------------------------------------
    page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const card = el.shadowRoot && el.shadowRoot.querySelector('[data-zone="e1"]');
            if (card) {
              [...card.querySelectorAll('button')].find(b => b.dataset.action === 'calibrate').click();
              return true;
            }
          }
          return false;
        }"""
    )
    page.wait_for_function(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const d = el.shadowRoot && el.shadowRoot.querySelector('dialog.fx-dialog');
            if (d) return true;
          }
          return false;
        }""",
        timeout=4000,
    )
    check("calibrate confirm dialog opens", True)
    page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const d = el.shadowRoot && el.shadowRoot.querySelector('dialog.fx-dialog');
            if (d) { [...d.querySelectorAll('button')].find(b => b.textContent === '开始校准').click(); return; }
          }
        }"""
    )
    page.wait_for_function(
        """() => (window.__serviceCalls || []).some(c => c.domain === 'lux_balance' && c.service === 'calibrate' && Array.isArray(c.data.entity_id))""",
        timeout=4000,
    )
    check("calibrate service called with entity_id list", True)

    # ---- 7: calibrating fixture ------------------------------------------------------
    page2 = browser.new_page(viewport={"width": 1280, "height": 900})
    page2.goto(base + "/?calibrating=1")
    page2.wait_for_timeout(900)
    text = page2.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const card = el.shadowRoot && el.shadowRoot.querySelector('[data-zone="e2"]');
            if (card) return card.textContent;
          }
          return '';
        }"""
    )
    check("calibrating zone shows progress", "上行 55%" in text, text[:100])
    check("calibrating note present", "其他区域闭环自动让路" in text, "")
    # 校准互斥第一道防线：任一区域校准中 → 其他区域的校准按钮禁用（LX-F-002）
    dis = page2.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const card = el.shadowRoot && el.shadowRoot.querySelector('[data-zone="e1"]');
            if (card) {
              const b = [...card.querySelectorAll('button')].find(x => x.dataset.action === 'calibrate');
              return b ? {disabled: b.disabled, title: b.title || ''} : null;
            }
          }
          return null;
        }"""
    )
    check("other zone calibrate button disabled while calibrating",
          dis and dis["disabled"] is True and "一次只能校准" in dis["title"], str(dis))
    page2.close()

    # ---- 7b: nocurve 空态 ------------------------------------------------------------
    page2b = browser.new_page(viewport={"width": 1280, "height": 900})
    page2b.goto(base + "/?nocurve=1")
    page2b.wait_for_function(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const card = el.shadowRoot && el.shadowRoot.querySelector('[data-zone="e1"]');
            if (card) return card.textContent.includes("尚未标定");
          }
          return false;
        }""",
        timeout=9000,
    )
    check("nocurve zone shows guided empty state", True)
    btn = page2b.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const card = el.shadowRoot && el.shadowRoot.querySelector('[data-zone="e1"]');
            if (card) {
              const b = [...card.querySelectorAll('button')].find(x => x.dataset.action === 'calibrate');
              return b ? b.textContent : null;
            }
          }
          return null;
        }"""
    )
    check("nocurve button says 开始校准 (not 重新校准)", btn == "开始校准", str(btn))
    page2b.close()

    # ---- 8: failapi --------------------------------------------------------------------
    page3 = browser.new_page(viewport={"width": 1280, "height": 900})
    page3.goto(base + "/?failapi=1")
    page3.wait_for_timeout(900)
    err = page3.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const c = el.shadowRoot && el.shadowRoot.querySelector('.fx-error');
            if (c) return {msg: c.querySelector('.msg').textContent, retry: !!c.querySelector('button')};
          }
          return null;
        }"""
    )
    check("failapi renders error card", err is not None, "no .fx-error")
    check("error card has retry", bool(err and err["retry"]), str(err))
    page3.close()

    # ---- 9: bad module --------------------------------------------------------------------
    page4 = browser.new_page(viewport={"width": 1280, "height": 900})
    page4.goto(base + "/?badmodule=1")
    page4.wait_for_timeout(900)
    card = page4.evaluate(
        """() => {
          const c = document.getElementById('hub').shadowRoot.querySelector('.fx-error');
          return c ? {msg: c.querySelector('.msg').textContent, retry: !!c.querySelector('button')} : null;
        }"""
    )
    check("bad module shows shell error card", card is not None, "no .fx-error")
    check("shell error card has retry", bool(card and card["retry"]), str(card))
    page4.close()

    # ---- 10: standalone fallback -------------------------------------------------------------
    page5 = browser.new_page(viewport={"width": 1280, "height": 900})
    page5.goto(base + "/?standalone=1")
    page5.wait_for_function(
        """() => {
          const el = document.getElementById('page');
          return el && el.shadowRoot && el.shadowRoot.querySelector('[data-zone="e1"]') !== null;
        }""",
        timeout=9000,
    )
    check("standalone fallback boots from vendored kit/tokens", True)
    page5.close()

    # ---- F-030/LX-F-031 regression pins ---------------------------------------
    # (a) error card lifecycle on THIS page: fail ON -> >=3 failing refreshes
    # (past the failStreak gate) -> card shows; fail OFF -> one refresh must
    # replace the card with the regular render even though the payload is
    # byte-identical to pre-failure (the LX-F-020 recovery gate).
    page.evaluate("() => window.__setFailApi(true)")
    page.evaluate(
        """async () => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.tagName.toLowerCase() === 'lux-balance-page') {
              for (let i = 0; i < 4; i++) { await el._refresh(); }
              return;
            }
          }
        }"""
    )
    page.wait_for_function(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.shadowRoot && el.shadowRoot.querySelector('.fx-error')) return true;
          }
          return false;
        }""",
        timeout=6000,
    )
    check("error card shows after fail streak", True)
    page.evaluate("() => window.__setFailApi(false)")
    page.evaluate(
        """async () => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.tagName.toLowerCase() === 'lux-balance-page') {
              await el._refresh();
              return;
            }
          }
        }"""
    )
    page.wait_for_function(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.shadowRoot && el.shadowRoot.querySelector('[data-zone="e1"]')) return true;
          }
          return false;
        }""",
        timeout=6000,
    )
    recovered = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.shadowRoot) {
              return {
                errorGone: !el.shadowRoot.querySelector('.fx-error'),
                zoneBack: !!el.shadowRoot.querySelector('[data-zone="e1"]'),
              };
            }
          }
          return null;
        }"""
    )
    check("error card replaced by regular render after recovery",
          bool(recovered and recovered["errorGone"] and recovered["zoneBack"]), str(recovered))

    # (b) curve with dirty scalars: chips hidden, axis falls back to points max
    page.evaluate("() => window.__setDirtyScalars(true)")
    page.evaluate(
        """async () => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.tagName.toLowerCase() === 'lux-balance-page') {
              await el._refresh();
              return;
            }
          }
        }"""
    )
    page.wait_for_function(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.shadowRoot && el.shadowRoot.querySelector('[data-zone="e1"] svg')) return true;
          }
          return false;
        }""",
        timeout=6000,
    )
    dirty = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const card = el.shadowRoot && el.shadowRoot.querySelector('[data-zone="e1"]');
            if (card) {
              const svg = card.querySelector('svg');
              const poly = svg && svg.querySelector('polyline');
              return {
                noNullChip: !card.textContent.includes('null'),
                hasCurveChip: card.textContent.includes('标定曲线'),
                polyPoints: poly ? poly.getAttribute('points').trim().split(' ').length : 0,
              };
            }
          }
          return null;
        }"""
    )
    check("dirty scalars: no null chips, curve still plotted",
          bool(dirty and dirty["noNullChip"] and dirty["hasCurveChip"] and dirty["polyPoints"] == 6), str(dirty))

    check("no page errors so far", not errors, "; ".join(errors[:3]))

    # ---- 11: screenshots -----------------------------------------------------------------------
    shots = [
        ("/", "p1-light-desktop.png", 1280, 900),
        ("/?dark=1", "p1-dark-desktop.png", 1280, 900),
        ("/", "p1-light-narrow.png", 390, 844),
        ("/?dark=1", "p1-dark-narrow.png", 390, 844),
    ]
    for path, name, w, h in shots:
        sp = browser.new_page(viewport={"width": w, "height": h})
        sp.goto(base + path)
        sp.wait_for_timeout(900)
        sp.screenshot(path=str(SHOTS / name), full_page=False)
        sp.close()
        check(f"shot {name}", (SHOTS / name).is_file())

    page.close()


if __name__ == "__main__":
    raise SystemExit(main())
