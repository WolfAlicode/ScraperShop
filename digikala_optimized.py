import json
import time
import random
import logging
from urllib.parse import urlencode, urljoin
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# Logging settings
logger = logging.getLogger("digikala_scraper")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
)

file_handler = logging.FileHandler("digikala_scraper.log", encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


# Helper functions

def build_digikala_search_url(query: str) -> str:
    base_url = "https://www.digikala.com/search/"
    params = {"q": query}
    return f"{base_url}?{urlencode(params)}"


def extract_price_from_text(text: str) -> int | None:
    """Convert price text to integer"""
    if not text:
        return None
    text = text.replace(",", "").replace("٬", "")
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


# Fetch HTML with Playwright
def fetch_page_playwright(url: str, delay=4, timeout=60000):
    """Fetch HTML using a real browser (to avoid timeout errors)"""
    for attempt in range(3):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0 Safari/537.36"
                ))
                page = context.new_page()
                logger.info(f"🌐 Attempt {attempt + 1}: loading page {url}")

                page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                time.sleep(delay + random.uniform(1, 3))  # natural delay

                html = page.content()
                browser.close()
                logger.info("✅ Page loaded successfully.")
                return 200, html

        except Exception as e:
            logger.warning(f"⚠️ Error on attempt {attempt + 1}: {e}")
            time.sleep(3 + attempt * 2)

    logger.error(f"❌ Failed to fetch page after 3 attempts: {url}")
    return 500, None


# Search and extract products
def digikala_search_and_extract(query, max_results=10):
    search_url = build_digikala_search_url(query)
    logger.info(f"🔍 Starting search for '{query}' → {search_url}")

    status, html = fetch_page_playwright(search_url, delay=4)
    if status != 200 or not html:
        logger.error("❌ Error fetching search page data.")
        return []

    soup = BeautifulSoup(html, "lxml")
    products = soup.select("a[href*='/product/']")

    results = []
    seen = set()

    logger.info("🔹 Extracting product information...")

    for link in products[: max_results * 2]:
        href = link.get("href")
        if not href or href in seen:
            continue
        seen.add(href)
        full_url = urljoin(search_url, href)

        # title
        title_el = link.select_one("h3.ellipsis-2")
        title = title_el.get_text(strip=True) if title_el else None

        # price
        price_el = link.select_one("span[data-testid='price-final']")
        price_raw = price_el.get_text(strip=True) if price_el else None
        price_toman = extract_price_from_text(price_raw)

        if title:
            results.append({
                "title": title,
                "price_toman": price_toman,
                "url": full_url
            })
            logger.info(f"✅ Product: {title[:60]} | 💰 {price_toman if price_toman else 'Unknown'} Toman")

        if len(results) >= max_results:
            break

    logger.info(f"📦 {len(results)} final results obtained.")
    return results


# Function for bot
def search(query: str, max_results: int = 10):
    """Function compatible with bot_final.py"""
    try:
        logger.info(f"🔎 Running search() for '{query}'")
        return digikala_search_and_extract(query, max_results=max_results)
    except Exception as e:
        logger.exception(f"❌ Error in digikala search() function: {e}")
        return [{"title": "Search error", "url": "#", "price": str(e)}]


# Direct execution

if __name__ == "__main__":
    logger.info("🔹 Running Digikala scraper directly (with logging)")
    q = input("🔍 Search query: ") or "mobile phone"
    n_input = input("🔢 Number of results (default 5): ").strip()
    n = int(n_input) if n_input.isdigit() else 5

    data = search(q, max_results=n)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    logger.info("✅ Scraper finished successfully.")
