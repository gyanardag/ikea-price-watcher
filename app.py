from flask import Flask, render_template, request, jsonify
from playwright.sync_api import sync_playwright
import concurrent.futures
import os

app = Flask(__name__)

# IKEA URL Templates
URL_TEMPLATES = {
    'BE': 'https://www.ikea.com/be/en/p/{id}/',
    'NL': 'https://www.ikea.com/nl/en/p/{id}/',
    'FR': 'https://www.ikea.com/fr/fr/p/{id}/',
    'DE': 'https://www.ikea.com/de/en/p/{id}/'
}

def get_price_via_browser(country_data):
    country_code, item_id = country_data
    clean_id = item_id.replace('.', '').replace(' ', '')
    url = URL_TEMPLATES[country_code].format(id=clean_id)
    
    p = sync_playwright().start()
    browser = None
    try:
        # Optimized for Cloud (Render) RAM limits while keeping local compatibility
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", 
                "--disable-setuid-sandbox", 
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # Cloud Optimization: Block unnecessary heavy resources but KEEP images for the UI
        def handle_route(route):
            if route.request.resource_type in ["font", "media"]:
                route.abort()
            else:
                route.fallback()

        page.route("**/*", handle_route)
        
        # Increase timeout for slow cloud environments
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        
        # Scrape Price
        price_selectors = [".pip-price__integer", ".pipcom-price__integer", ".pip-temp-price-weighted__integer"]
        price_text = None
        for sel in price_selectors:
            el = page.query_selector(sel)
            if el:
                price_text = el.inner_text().strip()
                break
        
        # Scrape Product Name
        name_el = page.query_selector("h1, .pip-header-section__title--big")
        name = name_el.inner_text().strip() if name_el else "IKEA Item"

        # Scrape Product Image (Restored and fixed)
        image_url = None
        img_el = page.query_selector("img.pip-image")
        if img_el:
            # Check for high-res srcset first, fallback to src
            srcset = img_el.get_attribute("srcset")
            if srcset:
                image_url = srcset.split(',')[0].split(' ')[0].strip()
            else:
                image_url = img_el.get_attribute("src")
        
        if image_url and image_url.startswith('//'):
            image_url = "https:" + image_url

        parsed_price = None
        if price_text:
            try:
                # Handle different European decimal separators
                parsed_price = float(price_text.replace(',', '.').replace(' ', ''))
            except ValueError:
                parsed_price = None

        return country_code, {
            "price": parsed_price, 
            "display_price": f"€{price_text}" if price_text else "N/A",
            "name": name,
            "image": image_url,
            "url": url,
            "status": "success" if price_text else "error"
        }

    except Exception as e:
        print(f"Error [{country_code}]: {str(e)}")
        return country_code, {"price": None, "display_price": "Error", "name": "-", "status": "error", "url": url}
    finally:
        if browser: browser.close()
        p.stop()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/compare', methods=['POST'])
def compare():
    data = request.get_json()
    item_id = data.get('item_id')
    results = {}
    tasks = [(code, item_id) for code in URL_TEMPLATES.keys()]
    
    # max_workers=2 is the sweet spot for 512MB RAM on Render
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_to_code = {executor.submit(get_price_via_browser, task): task[0] for task in tasks}
        for future in concurrent.futures.as_completed(future_to_code, timeout=120):
            code, res = future.result()
            results[code] = res

    # Sync French Product names to English for consistency
    eng_name = next((results[c]['name'] for c in ['NL','BE','DE'] if results.get(c,{}).get('status')=='success'), None)
    if eng_name:
        for c in results:
            if results[c]['status'] == 'success':
                results[c]['name'] = eng_name

    return jsonify(results)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    # debug=True enabled for local troubleshooting
    app.run(host='0.0.0.0', port=port, debug=True)