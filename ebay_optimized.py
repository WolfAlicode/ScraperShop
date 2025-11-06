import json, logging, time, random
from urllib.parse import urljoin, quote_plus
from bs4 import BeautifulSoup
import re

# PROFESSIONAL LOGGER SETTINGS
logger = logging.getLogger("ebay_scraper")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

# Prevent duplicate handlers if module reloaded
if not logger.handlers:
    file_handler = logging.FileHandler("ebay_scraper.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# PLAYWRIGHT IMPORT. REQUIRED FOR SCRAPING
try:
    from playwright.sync_api import sync_playwright
except Exception:
    raise RuntimeError("⚠️ Please install: pip install playwright && playwright install chromium")


# Regex for detecting price formats
price_re = re.compile(r'([$€£]\s?[\d,]+(?:\.\d{1,2})?)')

#  PRICE PARSER
def extract_price_from_text(text):
    """Extract numerical price value from mixed text."""
    if not text:
        return None
    
    match = price_re.search(text)
    if not match:
        return None
    
    raw = match.group(1).replace("$", "").replace(",", "").strip()
    try:
        return float(raw)
    except Exception as e:
        logger.warning(f"Price conversion error: {e}")
        return None

#  URL BUILDER FOR EBAY SEARCH
def build_ebay_search_url(query):
    """Build a valid eBay search URL from a query string."""
    return f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(query)}"

# SMART PAGE LOADER (PLAYWRIGHT)
def fetch_page_playwright(page, url, selector=None, timeout=20000, random_delay=True):
    """
    Load a page using Playwright with optional selector waiting
    and a natural/random delay to reduce bot detection.
    """
    try:
        logger.info(f"🌐 Loading page: {url}")
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")

        if selector:
            logger.info(f"⏳ Waiting for selector: {selector}")
            page.wait_for_selector(selector, timeout=timeout)

        html = page.content()

        if random_delay:
            d = random.uniform(0.5, 2.0)
            logger.info(f"⏱ Random delay: {d:.2f}s")
            time.sleep(d)

        return html

    except Exception as e:
        logger.warning(f"⚠️ Failed loading {url}: {e}")
        return None
#SINGLE PRODUCT PARSER
def extract_product_from_html(html):
    """
    Extract product title and price from product page HTML.
    Includes LD+JSON reading for high accuracy.
    """
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else None
    price = None

    #Check structured JSON-LD first
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "{}")
        except Exception:
            continue

        if isinstance(data, dict) and data.get("@type", "").lower() == "product":
            title = data.get("name", title)

            offers = data.get("offers")
            if offers and isinstance(offers, dict):
                p = extract_price_from_text(str(offers.get("price")))
                if p:
                    price = p

    #Check typical price elements if needed
    if not price:
        price_el = soup.select_one(".x-price-approx__price, .x-price-primary span, .display-price, .notranslate, .x-price-section span")
        if price_el:
            price = extract_price_from_text(price_el.get_text(strip=True))

    #Final fallback = scan entire page text
    if not price:
        price = extract_price_from_text(soup.get_text(" ", strip=True))

    return title, price

#MAIN SCRAPER
def ebay_scraper_full(query, n=10):
    start = time.time()

    logger.info("=" * 60)
    logger.info(f"🚀 Starting scrape for '{query}'")

    search_url = build_ebay_search_url(query)
    logger.info(f"🔍 Searching at: {search_url}")

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        #Load search results page
        html = fetch_page_playwright(page, search_url, selector="ul.srp-results")
        if not html:
            logger.error("❌ Failed to fetch search results page")
            browser.close()
            return []

        soup = BeautifulSoup(html, "lxml")

        #Collect product links
        links = []
        for a in soup.select("a[href*='/itm/']"):
            full_url = urljoin(search_url, a["href"].split("?")[0])
            if full_url not in links:
                links.append(full_url)
            if len(links) >= n:
                break

        logger.info(f"🔹 {len(links)} product links found → Fetching details...")
        # Extract each product
        for i, url in enumerate(links, start=1):
            try:
                html2 = fetch_page_playwright(page, url, selector=".x-price-section, .x-item-title")
                if not html2:
                    logger.warning(f"⚠️ Skipping (no response): {url}")
                    continue

                title, price = extract_product_from_html(html2)

                results.append({
                    "title": title or "Unknown Title",
                    "price_dollar": price,
                    "url": url
                })

                logger.info(f"✅ {i}/{len(links)} → {title[:60] if title else 'No Title'} | ${price if price else '???'}")

            except Exception as e:
                logger.exception(f"⚠️ Error extracting {url}: {e}")

        browser.close()

    elapsed = time.time() - start
    logger.info(f"🏁 Finished! Results: {len(results)} | Time: {elapsed:.2f}s")
    logger.info("=" * 60)

    return results


#BOT API WRAPPER
def search(query: str, max_results: int = 5):
    """
    Bot-facing function that formats prices nicely
    and ensures clean output for messaging systems.
    """
    try:
        logger.info(f"🔎 Running search() for '{query}'")
        raw = ebay_scraper_full(query, n=max_results)

        final = []
        for r in raw:
            final.append({
                "title": r.get("title"),
                "url": r.get("url"),
                "price": f"${r.get('price_dollar')}" if r.get("price_dollar") else "Unknown"
            })
        return final

    except Exception as e:
        logger.exception(f"❌ eBay search() failed: {e}")
        return []


#COMMAND-LINE MODE

if __name__ == "__main__":
    logger.info("🔹 Running eBay scraper directly (CLI Mode)")
    query = input("🔍 Search query: ").strip()
    n_input = input("🔢 Number of results (default 10): ").strip()
    n = int(n_input) if n_input.isdigit() else 10

    logger.info(f"Starting query '{query}' with {n} results...")
    out = ebay_scraper_full(query, n=n)

    logger.info(f"📦 Received {len(out)} products.")
    print(json.dumps(out, ensure_ascii=False, indent=2))
