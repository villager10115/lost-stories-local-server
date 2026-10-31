import argparse
import json

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp-url", required=True)
    parser.add_argument("--match", default="")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp_url)
        pages = [
            page for context in browser.contexts for page in context.pages
            if not args.match or args.match in page.url
        ]
        if not pages:
            raise SystemExit("No matching CDP page")
        page = pages[0]
        state = page.evaluate(
            """() => ({
                href: location.href,
                title: document.title,
                hash: location.hash,
                text: String(document.body && document.body.innerText || "")
                    .replace(/\\s+/g, " ").trim().slice(0, 5000),
                dialogs: Array.from(document.querySelectorAll(
                    "[role=dialog],.popupInner,[id*=Popup]"))
                    .map(element => String(element.innerText || "").trim())
                    .filter(Boolean).slice(0, 10)
            })"""
        )
        print(json.dumps(state, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
