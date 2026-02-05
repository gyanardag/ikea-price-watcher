from flask import Flask, render_template, request, jsonify
from playwright.sync_api import sync_playwright
import concurrent.futures
import os

app = Flask(__name__)

# IKEA URL Templates - FR uses /fr/fr/ because /fr/en/ does not exist
URL_TEMPLATES = {
    'BE': 'https://www.ikea.com/be/en/p/{id}/',
    'NL': 'https://www.ikea.com/nl/en/p/{id}/',
    'FR': 'https://www.ikea.com/fr/fr/p/{id}/', # No English option for FR
    'DE': 'https://www.ikea.com/de/en/p/{id}/'
}

def get_price_via_browser(country_data):
    """
    Fetches product details. Specifically handles the absence of English on IKEA FR.
    """
    country_code, item_id = country_data
    clean_id = item_id.replace('.', '').replace(' ', '')
    url = URL_TEMPLATES[country_code].format(id=clean_id)
    
    p = sync_playwright().start()
    browser = None
    try:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            ignore_https_errors=True
        )
        page = context.new_page()

        # Block non-essential resources to maintain speed
        def handle_route(route):
            if route.request.resource_type in ["font", "media", "manifest"]:
                route.abort()
            elif any(x in route.request.url for x in ["analytics", "doubleclick", "facebook", "google-analytics"]):
                route.abort()
            else:
                route.fallback()

        page.route("**/*", handle_route)
        page.goto(url, timeout=25000, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        # 1. Scrape Price (IKEA uses the same classes globally)
        price_selectors = [".pipcom-price__integer", ".pip-price__integer", ".pip-temp-price-weighted__integer"]
        price = None
        for selector in price_selectors:
            el = page.query_selector(selector)
            if el:
                price = el.inner_text().strip()
                break
        
        # 2. Scrape Product Name
        name_el = page.query_selector("h1, .pip-header-section__title--big")
        name = name_el.inner_text().strip() if name_el else "IKEA Product"

        # 3. Scrape Product Image (Robust Logic)
        image_url = None
        img_selectors = ["img.pipf-image", "img.pip-image", ".pip-aspect-ratio-box__target"]
        for sel in img_selectors:
            img_el = page.query_selector(sel)
            if img_el:
                srcset = img_el.get_attribute("srcset")
                if srcset:
                    image_url = srcset.split(',')[0].split(' ')[0].strip()
                if not image_url or "false" in str(image_url):
                    image_url = img_el.get_attribute("src")
                if image_url:
                    if image_url.startswith('//'): image_url = "https:" + image_url
                    break
        
        parsed_price = None
        if price:
            try:
                parsed_price = float(price.replace(',', '.'))
            except ValueError:
                parsed_price = None

        return country_code, {
            "price": parsed_price, 
            "display_price": f"€{price}" if price else "N/A",
            "name": name,
            "image": image_url,
            "url": url,
            "status": "success" if price else "error"
        }

    except Exception as e:
        print(f"Error [{country_code}]: {str(e)}")
        return country_code, {"price": None, "display_price": "Timeout", "name": "-", "status": "error", "url": url}
    finally:
        if browser: browser.close()
        p.stop()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/compare', methods=['POST'])
def compare():
    item_id = request.json.get('item_id')
    results = {}
    tasks = [(code, item_id) for code in URL_TEMPLATES.keys()]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_code = {executor.submit(get_price_via_browser, task): task[0] for task in tasks}
        try:
            for future in concurrent.futures.as_completed(future_to_code, timeout=35):
                code, data = future.result()
                results[code] = data
        except concurrent.futures.TimeoutError:
            pass

    # --- Language Fix Logic ---
    # Find a name from a country that IS in English (BE, NL, or DE)
    english_name = None
    for code in ['NL', 'BE', 'DE']:
        if code in results and results[code]['status'] == 'success':
            english_name = results[code]['name']
            break
    
    # If we found an English name, force it onto the French result (and others)
    if english_name:
        for code in results:
            if results[code]['status'] == 'success':
                results[code]['name'] = english_name

    for code in URL_TEMPLATES.keys():
        if code not in results:
            results[code] = {"price": None, "display_price": "N/A", "name": "-", "status": "error", "url": URL_TEMPLATES[code].format(id=item_id)}
            
    return jsonify(results)

if __name__ == '__main__':
    app.run(debug=True)