import requests, re, json, time, logging
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote_plus
from playwright.sync_api import sync_playwright
#این قسمت به دلیل حساسیت گیت هاب کلمات مودبانه تر و کمتر مورد استفاده قرار گرفته این کلمات جایگزین کنید
FORBIDDEN_WORDS = {
    "porn", "sex", "xxx", "adult", "nsfw", "erotic", "fetish",
    "hentai", "bdsm", "hardcore", "nude", "explicit", "18+", "mature",
    "پورنو", "پورنوگرافی", "محتوای بزرگسال", "محتوای ۱۸",
    "محتوای جنسی", "روابط جنسی", "مستهجن", "شهوانی"
}

def contains_forbidden(text: str):
    if not text:
        return False
    t = text.lower()
    return any(bad in t for bad in FORBIDDEN_WORDS)

# Professional logging settings
logger = logging.getLogger("web_mimic_optimized")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
)

if not logger.handlers:
    file_handler = logging.FileHandler("web_mimic_optimized.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

#  setting Regex
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
}

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
price_re = re.compile(r"([0-9۰-۹\.,\s]+)\s*(تومان|ت|Toman|IRR|ریال)?", re.I)

def normalize_digits(s):
    return s.translate(PERSIAN_DIGITS) if s else s

def extract_price_from_text(text):
    if not text:
        return None
    text = normalize_digits(text)
    m = price_re.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "").replace(".", "").replace(" ", "")
    try:
        return int(raw)
    except Exception as e:
        logger.warning(f"Error converting price:{e}")
        return None

#  search at DuckDuckGo
def duckduckgo_search(query, site=None, max_results=10, pause=0.4):
    q = query
    if site:
        domain = urlparse(site).netloc
        q = f"site:{domain} {query}"

    url = f"https://html.duckduckgo.com/html/?q={quote_plus(q)}"
    logger.info(f"🔍 search inDuckDuckGo: {q}")

    resp = requests.post(url, data={"q": q}, headers=HEADERS, timeout=20)
    time.sleep(pause)

    if resp.status_code != 200:
        logger.error(f"❌ Search error ({resp.status_code})")
        raise RuntimeError(f"Search failed: {resp.status_code}")

    soup = BeautifulSoup(resp.text, "lxml")
    exclude = ["category", "search", "filter", "collections", "tag"]
    include = ["product", "item", "sku", "detail", "p/"]

    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        href_l = href.lower()
        if any(e in href_l for e in exclude):
            continue
        if not any(i in href_l for i in include):
            continue
        clean = href.split("?")[0].rstrip("/")
        if clean not in urls:
            urls.append(clean)
        if len(urls) >= max_results:
            break

    logger.info(f"🔹 {len(urls)} product links found.")
    return urls

#  بارگذاری صفحات با Playwright
def fetch_page_playwright(url, timeout=25000):
    try:
        logger.info(f"🌐 Loading page: {url}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"accept-language": "fa-IR,fa;q=0.9"})
            page.goto(url, timeout=timeout)
            time.sleep(1.5)
            html = page.content()

            if "تومان" not in html and "price" not in html.lower():
                time.sleep(0.5)
                html = page.content()

            browser.close()
            return html
    except Exception as e:
        logger.exception(f"❌ Error loading {url}: {e}")
        return None

#  Extract information from HTML
def extract_product_from_html(html):
    soup = BeautifulSoup(html, "lxml")
    title, price = None, None

    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "{}")
        except Exception:
            continue
        data_list = data if isinstance(data, list) else [data]
        for it in data_list:
            if isinstance(it, dict) and it.get("@type", "").lower() == "product":
                title = it.get("name") or it.get("headline")
                offers = it.get("offers")
                if offers:
                    of = offers[0] if isinstance(offers, list) else offers
                    pr = of.get("price") or of.get("priceSpecification", {}).get("price")
                    if pr:
                        price = extract_price_from_text(str(pr))
                break

    if not title and soup.title:
        title = soup.title.get_text(strip=True)
    if not price:
        for tag in ["span", "div", "meta", "bdi"]:
            for el in soup.find_all(tag):
                txt = el.get("content") or el.get_text(" ", strip=True)
                p = extract_price_from_text(txt)
                if p:
                    price = p
                    break
            if price:
                break

    return {"title": title, "price_toman": price}

#  Main search function
def search(site, query, max_results=5):
    start_time = time.time()
    logger.info("=" * 60)
    logger.info(f"🚀 Starting search for '{query}' on site '{site}'")

    # Input validation in all cases (CLI)
    if contains_forbidden(site) or contains_forbidden(query):
        logger.warning(f"⛔ Invalid input: site={site}, query={query}")
        return [{
            "title": "⛔ Invalid content",
            "url": "#",
            "price": "Input contains forbidden words."
        }]

    try:
        urls = duckduckgo_search(query, site=site, max_results=max_results)
        results = []
        for i, u in enumerate(urls, 1):
            try:
                html = fetch_page_playwright(u)
                if not html:
                    logger.warning(f"⏳ Failed to fetch: {u}")
                    continue
                data = extract_product_from_html(html)
                if not data["title"]:
                    continue
                results.append({
                    "title": data["title"],
                    "url": u,
                    "price": f"{data['price_toman']:,} تومان" if data["price_toman"] else "invalid"
                })
                logger.info(f"✅ {i}/{len(urls)} → {data['title'][:60]} | {data['price_toman'] or '???'} تومان")
            except Exception as e:
                logger.exception(f"⚠️ Error extracting {u}: {e}")

        elapsed = time.time() - start_time
        logger.info(f" Search completed | Results: {len(results)} | time: {elapsed:.2f}s")
        logger.info("=" * 60)
        return results
    except Exception as e:
        logger.exception(f"❌ Error in search function: {e}")
        return []

# Direct execution mode (CLI)
if __name__ == "__main__":
    logger.info("🔹 Direct execution of scraper (Production Mode)")
    site = input("🌐 Site URL: ").strip()
    query = input("🔍 Search: ").strip()

    if contains_forbidden(site) or contains_forbidden(query):
        print("\n⛔ Invalid content detected and not supported! ⛔")
        logger.warning(f"⚠️ Attempted invalid input → Site: {site} | Query: {query}")
        exit(0)

    data = search(site, query, max_results=5)
    logger.info(f"📦 {len(data)} final results received.")
    print(json.dumps(data, ensure_ascii=False, indent=2))
