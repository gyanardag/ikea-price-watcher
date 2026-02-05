from flask import Flask, render_template, request, jsonify
from playwright.sync_api import sync_playwright
import os

app = Flask(__name__)

# IKEA URL Templates
URL_TEMPLATES = {
    'BE': 'https://www.ikea.com/be/en/p/{id}/',
    'NL': 'https://www.ikea.com/nl/en/p/{id}/',
    'FR': 'https://www.ikea.com/fr/fr/p/{id}/',
    'DE': 'https://www.ikea.com/de/en/p/{id}/'
}

def scrape_product(page, country_code, item_id):
    """Scrapes a single product using an existing page instance."""
    clean_id = item_id.replace('.', '').replace(' ', '')
    url = URL_TEMPLATES[country_code].format(id=clean_id)
    
    try:
        # Navigate with a generous timeout
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        
        # Scrape Price
        price_selectors = [".pip-price__integer", ".pipcom-price__integer", ".pip-temp-price-weighted__integer"]
        price_text = None
        for sel in price_selectors:
            el = page.query_selector(sel)
            if el:
                price_text = el.inner_text().strip()
                break
        
        # Scrape Name
        name_el = page.query_selector("h1, .pip-header-section__title--big")
        name = name_el.inner_text().strip() if name_el else "IKEA Item"

        # Scrape Image
        image_url = None
        img_el = page.query_selector("img.pip-image")
        if img_el:
            srcset = img_el.get_attribute("srcset")
            image_url = srcset.split(',')[0].split(' ')[0].strip() if srcset else img_el.get_attribute("src")
        
        if image_url and image_url.startswith('//'):
            image_url = "https:" + image_url

        parsed_price = None
        if price_text:
            try:
                parsed_price = float(price_text.replace(',', '.').replace(' ', ''))
            except:
                parsed_price = None

        return {
            "price": parsed_price, 
            "display_price": f"€{price_text}" if price_text else "N/A",
            "name": name,
            "image": image_url,
            "url": url,
            "status": "success" if price_text else "error"
        }
    except Exception as e:
        print(f"Scrape Error [{country_code}]: {e}")
        return {"price": None, "display_price": "Error", "name": "-", "status": "error", "url": url}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/compare', methods=['POST'])
def compare():
    data = request.get_json()
    item_id = data.get('item_id')
    results = {}

    with sync_playwright() as p:
        # Launch ONE browser instance to save RAM
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # Optimization: Block heavy ads/trackers but keep images
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["font", "media"] else route.fallback())

        # Process countries one by one (Sequential is necessary for 512MB RAM)
        for code in URL_TEMPLATES.keys():
            results[code] = scrape_product(page, code, item_id)

        browser.close()

    # Consolidate product names to English where possible
    eng_name = next((results[c]['name'] for c in ['NL','BE','DE'] if results[c]['status'] == 'success'), None)
    if eng_name:
        for c in results:
            if results[c]['status'] == 'success':
                results[c]['name'] = eng_name

    return jsonify(results)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)