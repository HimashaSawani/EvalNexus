import os
import time
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = "docs/reports/screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # 1. Overview with Onboarding
        page.goto("http://127.0.0.1:8001/#overview")
        page.wait_for_selector("#view-overview")
        time.sleep(1.0)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "uat_onboarding_01_overview.png"))
        print("Captured uat_onboarding_01_overview.png")

        # 2. Test Studio - Demo Mode
        page.goto("http://127.0.0.1:8001/#test-studio")
        page.wait_for_selector("#view-test-studio")
        time.sleep(1.0)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "uat_onboarding_02_demo_mode.png"))
        print("Captured uat_onboarding_02_demo_mode.png")

        # 3. Test Studio - Custom Agent Mode with HTTP Spec Card Open
        page.click("#btnModeCustom")
        time.sleep(0.5)
        page.click("#btnHttpSpec")
        time.sleep(0.5)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "uat_onboarding_03_custom_agent_mode.png"))
        print("Captured uat_onboarding_03_custom_agent_mode.png")

        # 4. Custom Agents View with Actions
        page.goto("http://127.0.0.1:8001/#custom-agents")
        page.wait_for_selector("#view-custom-agents")
        time.sleep(1.0)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "uat_onboarding_04_custom_agent_registry.png"))
        print("Captured uat_onboarding_04_custom_agent_registry.png")

        browser.close()

if __name__ == "__main__":
    main()

