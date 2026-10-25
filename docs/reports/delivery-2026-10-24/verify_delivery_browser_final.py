from pathlib import Path
source = Path(r'D:\AgentWindTunnel\docs\reports\delivery-2026-10-24\verify_delivery_v2.py').read_text(encoding='utf-8').rsplit("\nif __name__ == '__main__':", 1)[0]
exec(source)
# Active polling makes network-idle an unsuitable navigation readiness condition.
browser_source = globals()['source']
browser_source = browser_source.replace("wait_until='networkidle'", "wait_until='domcontentloaded'")
browser_source = browser_source.replace("            page.goto('http://127.0.0.1:8765',", "            page.set_default_timeout(60000)\n            page.set_default_navigation_timeout(60000)\n            page.goto('http://127.0.0.1:8765',")
browser_source = browser_source.replace("            page.screenshot(path=str(REPORT / 'desktop-empty.png')", "            page.wait_for_function('document.querySelector(\"#modelSelect\").options.length > 0')\n            page.screenshot(path=str(REPORT / 'desktop-empty.png')")
browser_source = browser_source.replace("            page.select_option('#providerSelect', 'mock')", "            page.wait_for_function('document.querySelector(\"#agentSelect\").options.length >= 3')\n            page.select_option('#providerSelect', 'mock')\n            page.select_option('#modelSelect', 'mock-deterministic-v1')")
browser_source = browser_source.replace("timeout=180000", "timeout=240000")
browser_source = browser_source.replace("            record('Desktop and 390px viewport screenshots captured')", "            record('Desktop and 390px viewport screenshots captured')\n            page.goto('http://127.0.0.1:8765/#test-studio?run=missing-verification-run', wait_until='domcontentloaded')\n            page.wait_for_function('document.querySelector(\"#panelRunStatusPill\").textContent.includes(\"HTTP 404\")')\n            page.screenshot(path=str(REPORT / 'missing-run-error.png'), full_page=True)\n            record('Missing run produces visible HTTP 404 error state')")
exec(browser_source)
browser()
