from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Sequence


def _default_bundle_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "declare-js.min.js"


def _read_constraint_lines_from_minerful_csv(csv_path: Path) -> list[str]:
    if not csv_path.exists():
        raise FileNotFoundError(f"MINERful CSV not found: {csv_path}")

    constraints: list[str] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=";", quotechar="'")
        for row in reader:
            if not row:
                continue
            candidate = (row[0] or "").strip().strip("'").strip('"')
            if not candidate:
                continue
            if candidate.lower() == "constraint":
                continue
            constraints.append(candidate)

    if not constraints:
        raise ValueError(f"No constraint lines parsed from MINERful CSV: {csv_path}")
    return constraints


def _build_html_document(
    *,
    declare_js_bundle: str,
    constraint_lines: Sequence[str],
    title: str,
) -> str:
    constraints_json = json.dumps(list(constraint_lines), ensure_ascii=False)
    title_safe = json.dumps(title, ensure_ascii=False)

    return (
        "<!doctype html>\n"
        "<html>\n"
        "<head>\n"
        '  <meta charset="utf-8">\n'
        f"  <title>{title}</title>\n"
        "  <style>\n"
        "    html, body { margin: 0; padding: 0; width: 100%; height: 100%; background: #fff; }\n"
        "    #declareContainer { width: 100%; height: 100vh; }\n"
        "    /* Hide declare-js bedienelemente (toolbar, action-buttons, file input) — */\n"
        "    /* the model itself remains visible. AUTO_LAYOUT click is JS-dispatched   */\n"
        "    /* and works even on display:none elements.                               */\n"
        "    [data-action], button[data-action], .toolbar, .menubar, .topbar,\n"
        "    header.toolbar, nav.menubar,\n"
        "    input[type=\"file\"], label.file-input { display: none !important; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        '  <div id="declareContainer"></div>\n'
        "  <script>\n"
        "    (function installDeclareWarningBridge() {\n"
        "      function ensureWarningBox() {\n"
        "        const container = document.getElementById('declareContainer') || document.body;\n"
        "        if (window.getComputedStyle(container).position === 'static') {\n"
        "          container.style.position = 'relative';\n"
        "        }\n"
        "        let box = document.getElementById('declareWarningBox');\n"
        "        if (!box) {\n"
        "          box = document.createElement('div');\n"
        "          box.id = 'declareWarningBox';\n"
        "          box.style.position = 'absolute';\n"
        "          box.style.top = '12px';\n"
        "          box.style.right = '12px';\n"
        "          box.style.maxWidth = '460px';\n"
        "          box.style.padding = '10px 12px';\n"
        "          box.style.border = '1px solid #f59e0b';\n"
        "          box.style.borderRadius = '8px';\n"
        "          box.style.background = '#fffbeb';\n"
        "          box.style.color = '#92400e';\n"
        "          box.style.fontFamily = 'Arial, sans-serif';\n"
        "          box.style.fontSize = '12px';\n"
        "          box.style.lineHeight = '1.35';\n"
        "          box.style.boxShadow = '0 4px 10px rgba(0, 0, 0, 0.08)';\n"
        "          box.style.display = 'none';\n"
        "          box.style.opacity = '0';\n"
        "          box.style.zIndex = '9999';\n"
        "          box.style.pointerEvents = 'none';\n"
        "          box.style.transition = 'opacity 0.25s ease';\n"
        "          container.appendChild(box);\n"
        "        }\n"
        "        return box;\n"
        "      }\n"
        "\n"
        "      window.__declareShowWarningToast = function showWarningToast(message) {\n"
        "        const box = ensureWarningBox();\n"
        "        box.textContent = String(message || 'declare-js issued a warning.');\n"
        "        box.style.display = 'block';\n"
        "        box.style.opacity = '1';\n"
        "        if (box.__hideTimer) {\n"
        "          window.clearTimeout(box.__hideTimer);\n"
        "        }\n"
        "        box.__hideTimer = window.setTimeout(() => {\n"
        "          box.style.opacity = '0';\n"
        "          window.setTimeout(() => {\n"
        "            box.style.display = 'none';\n"
        "          }, 260);\n"
        "        }, 6500);\n"
        "      };\n"
        "\n"
        "      const nativeAlert = window.alert ? window.alert.bind(window) : null;\n"
        "      window.__declareNativeAlert = nativeAlert;\n"
        "      window.alert = function patchedAlert(message) {\n"
        "        const text = String(message || '');\n"
        "        const isConstraintNormalization = /slightly changed to match the set of supported templates|AtLeast1|AtLeastOne/i.test(text);\n"
        "        if (isConstraintNormalization) {\n"
        "          window.__declareShowWarningToast('Warning: constraints were adjusted to the supported templates.');\n"
        "          console.warn('declare-js template normalization:', text);\n"
        "          return;\n"
        "        }\n"
        "        window.__declareShowWarningToast(text || 'Warning from declare-js');\n"
        "        console.warn('declare-js alert converted to warning box:', text);\n"
        "      };\n"
        "\n"
        "      // Global hide-controls helper: removes declare-js toolbar/buttons\n"
        "      // AND the right-side editor panel by default. Skipped when the\n"
        "      // host sets ``window.__declareFullscreen = true`` (modal view).\n"
        "      // Idempotent; safe to call multiple times.\n"
        "      window.__declareHideControls = function hideDeclareControls() {\n"
        "        if (window.__declareFullscreen) return;\n"
        "        try {\n"
        "          const actionBtns = document.querySelectorAll('[data-action]');\n"
        "          const parents = new Set();\n"
        "          actionBtns.forEach((btn) => {\n"
        "            btn.style.setProperty('display','none','important');\n"
        "            if (btn.parentElement) parents.add(btn.parentElement);\n"
        "          });\n"
        "          const root = document.getElementById('declareContainer') || document.body;\n"
        "          parents.forEach((p) => {\n"
        "            if (p === root) return;\n"
        "            if (p.querySelector('svg, canvas, g[class*=\"node\"], g[class*=\"link\"]')) return;\n"
        "            p.style.setProperty('display','none','important');\n"
        "          });\n"
        "          document.querySelectorAll('input[type=\"file\"], label.file-input')\n"
        "            .forEach((el) => el.style.setProperty('display','none','important'));\n"
        "          // The right-hand list = declare-js constraint editor. Selector\n"
        "          // matches its class (``editorContainer``) and a few common\n"
        "          // fallbacks for sidebars / right-rail wrappers.\n"
        "          document.querySelectorAll(\n"
        "            '.editorContainer, .editor-container, [class*=\"editor\"][class*=\"Container\"], '\n"
        "            + '.constraintList, .constraint-list, .sidebar, .rightPanel, .right-panel'\n"
        "          ).forEach((el) => {\n"
        "            // Skip the SVG canvas inside the editor, if any.\n"
        "            if (el.querySelector('svg, canvas')) return;\n"
        "            el.style.setProperty('display','none','important');\n"
        "          });\n"
        "        } catch (e) { /* never block the render on hide failure */ }\n"
        "      };\n"
        "    })();\n"
        "  </script>\n"
        "  <script>\n"
        f"{declare_js_bundle}\n"
        "  </script>\n"
        "  <script>\n"
        f"    const DECLARE_MODEL_TITLE = {title_safe};\n"
        f"    const DECLARE_CONSTRAINT_LINES = {constraints_json};\n"
        "    window.__declareCsvLoaded = false;\n"
        "    window.__declareAutoLayoutTriggered = false;\n"
        "    window.__declareAutoLayoutDone = false;\n"
        "    window.__declareBootstrapError = null;\n"
        "    function loadCsvIntoDeclareJs() {\n"
        "      const input = document.querySelector('input[type=\"file\"]');\n"
        "      if (!input) {\n"
        "        throw new Error('declare-js file input not found after initialization');\n"
        "      }\n"
        "      const csvPayload = 'Constraint\\n' + DECLARE_CONSTRAINT_LINES.join('\\n') + '\\n';\n"
        "      const file = new File([csvPayload], 'minerful_model.csv', { type: 'text/csv' });\n"
        "      const transfer = new DataTransfer();\n"
        "      transfer.items.add(file);\n"
        "      input.files = transfer.files;\n"
        "      input.dispatchEvent(new Event('change', { bubbles: true }));\n"
        "      window.__declareCsvLoaded = true;\n"
        "    }\n"
        "    function triggerAutoLayoutFromGear() {\n"
        "      const autoLayoutButton = document.querySelector('[data-action=\"AUTO_LAYOUT\"]');\n"
        "      if (!autoLayoutButton) {\n"
        "        throw new Error('declare-js AUTO_LAYOUT button not found');\n"
        "      }\n"
        "      const target = document.getElementById('declareContainer') || document.body;\n"
        "      const QUIET_MS = 350;\n"
        "      const MAX_AFTER_FIRST_MS = 2500;\n"
        "      const MAX_WAIT_MS = 4000;\n"
        "      let mutations = 0;\n"
        "      let quietTimer = null;\n"
        "      let firstMutationAt = 0;\n"
        "      let convergenceTimer = null;\n"
        "      const finish = () => {\n"
        "        if (window.__declareAutoLayoutDone) return;\n"
        "        observer.disconnect();\n"
        "        if (quietTimer) clearTimeout(quietTimer);\n"
        "        if (convergenceTimer) clearTimeout(convergenceTimer);\n"
        "        clearTimeout(safetyTimer);\n"
        "        window.__declareAutoLayoutDone = true;\n"
        "        if (window.__declareHideControls) window.__declareHideControls();\n"
        "      };\n"
        "      const isFromWarningBox = (node) => {\n"
        "        for (let n = node; n; n = n.parentNode) {\n"
        "          if (n && n.id === 'declareWarningBox') return true;\n"
        "        }\n"
        "        return false;\n"
        "      };\n"
        "      const observer = new MutationObserver((records) => {\n"
        "        let relevant = 0;\n"
        "        for (const r of records) {\n"
        "          if (!isFromWarningBox(r.target)) relevant += 1;\n"
        "        }\n"
        "        if (!relevant) return;\n"
        "        mutations += relevant;\n"
        "        if (!firstMutationAt) {\n"
        "          firstMutationAt = performance.now();\n"
        "          convergenceTimer = setTimeout(finish, MAX_AFTER_FIRST_MS);\n"
        "        }\n"
        "        if (quietTimer) clearTimeout(quietTimer);\n"
        "        quietTimer = setTimeout(() => {\n"
        "          if (mutations > 0) finish();\n"
        "        }, QUIET_MS);\n"
        "      });\n"
        "      observer.observe(target, { childList: true, subtree: true, attributes: true, characterData: true });\n"
        "      const safetyTimer = setTimeout(finish, MAX_WAIT_MS);\n"
        "      autoLayoutButton.dispatchEvent(new MouseEvent('click', {\n"
        "        bubbles: true,\n"
        "        cancelable: true,\n"
        "        view: window,\n"
        "      }));\n"
        "      window.__declareAutoLayoutTriggered = true;\n"
        "    }\n"
        "    window.addEventListener('load', () => {\n"
        "      setTimeout(() => {\n"
        "        try {\n"
        "          loadCsvIntoDeclareJs();\n"
        "          setTimeout(() => {\n"
        "            try {\n"
        "              triggerAutoLayoutFromGear();\n"
        "            } catch (error) {\n"
        "              window.__declareBootstrapError = String(error);\n"
        "              console.error('declare-js auto-layout trigger failed:', error);\n"
        "            }\n"
        "          }, 600);\n"
        "          document.title = DECLARE_MODEL_TITLE;\n"
        "        } catch (error) {\n"
        "          window.__declareBootstrapError = String(error);\n"
        "          console.error('declare-js bootstrap failed:', error);\n"
        "        }\n"
        "      }, 150);\n"
        "      // Belt-and-braces hide passes: catches late-mounting menu UI\n"
        "      // regardless of the auto-layout state.\n"
        "      [800, 2000, 4000].forEach((delay) => {\n"
        "        setTimeout(() => {\n"
        "          if (window.__declareHideControls) window.__declareHideControls();\n"
        "        }, delay);\n"
        "      });\n"
        "    });\n"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
    )


# pm4py declare template name → declare-js constraint name.
# pm4py emits lowercase keys (``response``, ``altprecedence``); declare-js
# accepts the CamelCase forms found in the bundle. ``log_skeleton`` constraints
# are not declare-js templates and stay unmapped → caller silently drops them.
_PM4PY_DECLARE_TEMPLATE_MAP: dict[str, str] = {
    "existence": "Existence",
    "exactly_one": "Exactly1",
    "init": "Init",
    "absence": "Absence",
    "responded_existence": "RespondedExistence",
    "response": "Response",
    "precedence": "Precedence",
    "succession": "Succession",
    "altresponse": "AlternateResponse",
    "altprecedence": "AlternatePrecedence",
    "altsuccession": "AlternateSuccession",
    "chainresponse": "ChainResponse",
    "chainprecedence": "ChainPrecedence",
    "chainsuccession": "ChainSuccession",
    "coexistence": "CoExistence",
    "noncoexistence": "NotCoExistence",
    "nonsuccession": "NotSuccession",
    "nonchainsuccession": "NotChainSuccession",
}


def _read_constraint_lines_from_pm4py_declare_json(json_path: Path) -> list[str]:
    """Convert a pm4py declare-miner JSON payload into declare-js constraint
    strings (``Response(a, b)`` form).

    Drops any constraint whose template is not in ``_PM4PY_DECLARE_TEMPLATE_MAP``
    (e.g. log-skeleton relations) so the renderer never crashes on unknowns.
    """
    if not json_path.exists():
        raise FileNotFoundError(f"pm4py declare JSON not found: {json_path}")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    raw_constraints = payload.get("constraints") if isinstance(payload, dict) else None
    if not isinstance(raw_constraints, list):
        raise ValueError(
            f"pm4py declare JSON missing 'constraints' list: {json_path}"
        )

    constraints: list[str] = []
    for entry in raw_constraints:
        if not isinstance(entry, dict):
            continue
        template = str(entry.get("template", "")).lower()
        mapped = _PM4PY_DECLARE_TEMPLATE_MAP.get(template)
        if not mapped:
            continue
        params = entry.get("parameters") or []
        # ``parameters`` is ``[[a, b]]`` for binary, ``[[a]]`` for unary.
        if isinstance(params, list) and params and isinstance(params[0], list):
            args = [str(x) for x in params[0]]
        else:
            args = [str(x) for x in (params or [])]
        if not args:
            continue
        constraints.append(f"{mapped}({', '.join(args)})")

    if not constraints:
        raise ValueError(
            f"pm4py declare JSON yielded zero renderable constraints: {json_path}"
        )
    return constraints


def render_declare_js_html_from_pm4py_json(
    *,
    json_path: Path,
    html_output_path: Path,
    title: str,
    bundle_path: Path | None = None,
) -> Path:
    """Render a pm4py declare-miner JSON output to a declare-js HTML page.

    Same shape as :func:`render_declare_js_html` (which reads MINERful CSV);
    factored separately because the parser differs.
    """
    bundle_file = (bundle_path or _default_bundle_path()).resolve()
    if not bundle_file.exists():
        raise FileNotFoundError(
            f"declare-js bundle not found: {bundle_file}. "
            "Expected internal/declarative_miner/assets/declare-js.min.js"
        )

    constraint_lines = _read_constraint_lines_from_pm4py_declare_json(json_path.resolve())
    bundle_code = bundle_file.read_text(encoding="utf-8")
    html = _build_html_document(
        declare_js_bundle=bundle_code,
        constraint_lines=constraint_lines,
        title=title,
    )

    html_output_path.parent.mkdir(parents=True, exist_ok=True)
    html_output_path.write_text(html, encoding="utf-8")
    return html_output_path


def render_declare_js_html(
    *,
    csv_path: Path,
    html_output_path: Path,
    title: str,
    bundle_path: Path | None = None,
) -> Path:
    bundle_file = (bundle_path or _default_bundle_path()).resolve()
    if not bundle_file.exists():
        raise FileNotFoundError(
            f"declare-js bundle not found: {bundle_file}. "
            "Expected internal/declarative_miner/assets/declare-js.min.js"
        )

    constraint_lines = _read_constraint_lines_from_minerful_csv(csv_path.resolve())
    bundle_code = bundle_file.read_text(encoding="utf-8")
    html = _build_html_document(
        declare_js_bundle=bundle_code,
        constraint_lines=constraint_lines,
        title=title,
    )

    html_output_path.parent.mkdir(parents=True, exist_ok=True)
    html_output_path.write_text(html, encoding="utf-8")
    return html_output_path


def render_declare_js_png(
    *,
    html_path: Path,
    png_output_path: Path,
    width: int = 1600,
    height: int = 980,
    wait_ms: int = 100,
    readiness_timeout_ms: int = 15_000,
) -> Path:
    if not html_path.exists():
        raise FileNotFoundError(f"declare-js HTML not found: {html_path}")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright is required for declare-js PNG rendering. "
            "Install with 'pip install playwright' and 'playwright install chromium'."
        ) from exc

    html_uri = html_path.resolve().as_uri()
    png_output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            page.goto(html_uri, wait_until="load", timeout=60_000)
            page.wait_for_function(
                "() => window.__declareAutoLayoutDone === true || !!window.__declareBootstrapError",
                timeout=readiness_timeout_ms,
            )
            bootstrap_error = page.evaluate("() => window.__declareBootstrapError")
            if bootstrap_error:
                raise RuntimeError(f"declare-js bootstrap error: {bootstrap_error}")
            page.wait_for_timeout(wait_ms)
            container = page.locator("#declareContainer")
            container.screenshot(path=str(png_output_path))
            if not page.evaluate("() => window.__declareAutoLayoutDone === true"):
                raise RuntimeError("declare-js snapshot was not taken after auto-layout completion")
        finally:
            page.close()
            browser.close()

    if not png_output_path.exists() or png_output_path.stat().st_size == 0:
        raise RuntimeError(f"declare-js PNG output is empty: {png_output_path}")
    return png_output_path
