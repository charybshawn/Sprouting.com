#!/usr/bin/env python3
import os
import csv
import time
import json
import re 
from urllib.parse import urljoin
from datetime import datetime
import logging
import logging.handlers 
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# --- Constants ---
BASE_SHOP_URL = "https://germina.ca/en/store/"
SUPPLIER_NAME = "germina_ca"
SHARED_OUTPUT_DIR = "./scraper_data/json_files/"
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "germina_scraper.log")
HEADLESS = True 
TEST_MODE = True 
TARGET_PRODUCT_CATEGORY_CLASS = "product_cat-organic-seeds"
BASE_URL_FOR_PRODUCTS = "https://germina.ca" # For resolving relative product URLs

# --- Known Cultivars Management ---
DEFAULT_CULTIVARS = sorted(list(set([
    "Alfalfa", "Amaranth", "Arugula", "Barley", "Basil", "Beet", "Bok Choy", "Borage", 
    "Broccoli", "Buckwheat", "Cabbage", "Carrot", "Celery", "Chervil", "Chia", "Chicory", 
    "Cilantro", "Clover", "Collard", "Coriander", "Corn Salad", "Cress", "Dill", 
    "Endive", "Fava Bean", "Fennel", "Fenugreek", "Flax", "Garlic Chives", "Kale", 
    "Kamut", "Kohlrabi", "Komatsuna", "Leek", "Lemon Balm", "Lentil", "Lettuce", 
    "Mache", "Melon", "Millet", "Mizuna", "Mung Bean", "Mustard", "Nasturtium", "Oat", 
    "Okra", "Onion", "Pak Choi", "Parsley", "Pea", "Peppergrass", "Perilla", "Popcorn", 
    "Poppy", "Purslane", "Quinoa", "Radish", "Rapini", "Red Shiso", "Rice", "Rocket", 
    "Rutabaga", "Rye", "Shiso", "Sorrel", "Spelt", "Spinach", "Sunflower", "Swiss Chard", 
    "Tatsoi", "Thyme", "Turnip", "Watercress", "Wheat", "Wheatgrass"
    # Add more common general cultivar names if needed
])))

# Determine the path for known_cultivars.csv in the scraper_data directory
# SHARED_OUTPUT_DIR is ./scraper_data/json_files/, so os.path.dirname(SHARED_OUTPUT_DIR) is ./scraper_data/
_scraper_data_dir = os.path.dirname(SHARED_OUTPUT_DIR)
if not _scraper_data_dir: # Fallback if SHARED_OUTPUT_DIR is at root like "./"
    _scraper_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraper_data")
CULTIVARS_CSV_FILEPATH = os.path.join(_scraper_data_dir, "known_cultivars.csv")

def save_known_cultivars_to_csv(filepath, cultivars_list):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        # Sort alphabetically for human readability in the CSV
        sorted_cultivars = sorted(list(set(c.strip() for c in cultivars_list if c and c.strip())))
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['cultivar_name']) # Header
            for cultivar in sorted_cultivars:
                writer.writerow([cultivar])
        logger.info(f"Saved {len(sorted_cultivars)} known cultivars to {filepath}")
    except Exception as e:
        logger.error(f"Error saving known cultivars to {filepath}: {e}")

def load_known_cultivars_from_csv(filepath):
    cultivars = []
    try:
        with open(filepath, 'r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            header = next(reader, None) # Skip header
            if header and header[0].lower().strip() != 'cultivar_name' and header[0].strip():
                 cultivars.append(header[0].strip()) # Not a header or empty, treat as data

            for row in reader:
                if row: # Ensure row is not empty
                    cultivar_name = row[0].strip()
                    if cultivar_name: # Ensure cultivar name is not empty
                        cultivars.append(cultivar_name)
        logger.info(f"Loaded {len(set(c for c in cultivars if c))} unique known cultivars from {filepath}")
    except FileNotFoundError:
        logger.warning(f"Known cultivars CSV not found at {filepath}. Initializing with default list and creating the file.")
        cultivars = list(DEFAULT_CULTIVARS) # Use a copy
        save_known_cultivars_to_csv(filepath, cultivars)
    except Exception as e:
        logger.error(f"Error loading known cultivars from {filepath}: {e}. Using default list.")
        cultivars = list(DEFAULT_CULTIVARS)

    # Remove duplicates and empty strings, then sort by length descending for matching
    unique_cultivars = sorted(list(set(c for c in cultivars if c)), key=len, reverse=True)

    if not unique_cultivars and DEFAULT_CULTIVARS:
        logger.warning(f"No valid cultivars loaded from {filepath} or CSV was empty. Re-initializing with defaults and saving.")
        unique_cultivars = sorted(list(set(c for c in DEFAULT_CULTIVARS if c)), key=len, reverse=True)
        save_known_cultivars_to_csv(filepath, unique_cultivars)
    
    return unique_cultivars

# Load KNOWN_CULTIVARS at startup
KNOWN_CULTIVARS = load_known_cultivars_from_csv(CULTIVARS_CSV_FILEPATH)

# --- Setup Logger ---
logger = logging.getLogger("GerminaScraper")
logger.setLevel(logging.INFO)

def setup_logging():
    """Configures logging to console and rotating file."""
    if not os.path.exists(LOG_DIR):
        try:
            os.makedirs(LOG_DIR)
        except OSError as e:
            print(f"Error creating log directory {LOG_DIR}: {e}")
            logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
            return

    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(message)s')

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'
        )
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Error setting up file logger: {e}")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)
    logger.info("Logging configured for Germina Scraper. Saving logs to: %s", LOG_FILE)

# --- Helper Functions (copied from sprouting_scraper.py and adapted/verified as needed) ---

def parse_cultivar_and_variety_from_title(title_string):
    """
    Parses cultivar and plant variety from a product title string.
    It removes 'organic' or 'biologique', then tries to split by common delimiters.
    If no delimiter, it uses a predefined list of KNOWN_CULTIVARS to identify the cultivar.
    Finally, it validates the found cultivar against KNOWN_CULTIVARS and standardizes casing.
    """
    if not title_string:
        return {"cultivar": "N/A", "plant_variety": "N/A"}

    # Remove "organic" or "biologique" case-insensitively and strip extra spaces
    processed_title = re.sub(r'\\b(organic|biologique)\\b', '', title_string, flags=re.IGNORECASE).strip()
    processed_title = ' '.join(processed_title.split()) # Normalize spaces

    cultivar = "N/A"
    plant_variety = "N/A"

    # Try splitting by comma or dash first
    delimiters = [',', '-']
    split_done = False
    for delimiter in delimiters:
        if delimiter in processed_title:
            parts = processed_title.split(delimiter, 1)
            if len(parts) == 2:
                cultivar = parts[0].strip()
                plant_variety = parts[1].strip()
                if cultivar and plant_variety: # Ensure both parts are non-empty
                    split_done = True
                    break
                elif cultivar and not plant_variety: # If only cultivar found, treat it as such
                    plant_variety = "N/A"
                    split_done = True
                    break
                elif not cultivar and plant_variety: # Unlikely, but handle
                    cultivar = plant_variety # Treat the second part as cultivar if first is empty
                    plant_variety = "N/A"
                    split_done = True
                    break
            elif len(parts) == 1 and parts[0].strip(): # Only one part after split
                cultivar = parts[0].strip()
                plant_variety = "N/A"
                split_done = True
                break
    
    if not split_done and processed_title: # If not split by delimiter and title is not empty
        if KNOWN_CULTIVARS:
            found_by_list = False
            for known_cult in KNOWN_CULTIVARS:
                # Case-insensitive match at the beginning of the string
                if re.match(rf'^{re.escape(known_cult)}\\b', processed_title, re.IGNORECASE):
                    cultivar = known_cult # Use the exact case from KNOWN_CULTIVARS for consistency
                    # The rest of the string is the variety
                    remaining_part = processed_title[len(known_cult):].strip()
                    if remaining_part:
                        plant_variety = remaining_part
                    else:
                        plant_variety = "N/A"
                    found_by_list = True
                    break
            if not found_by_list: # If no known cultivar matched
                cultivar = processed_title # Assign the whole processed title as cultivar
                plant_variety = "N/A"
        else: # No KNOWN_CULTIVARS list provided
            cultivar = processed_title
            plant_variety = "N/A"
    elif not cultivar and processed_title: # If split_done but cultivar is still N/A (e.g. from empty part before delimiter)
        cultivar = processed_title
        plant_variety = "N/A"

    # Standardize and Validate Cultivar
    final_cultivar = "N/A"
    standardized = False
    if cultivar and cultivar != "N/A":
        for known in KNOWN_CULTIVARS: # KNOWN_CULTIVARS is sorted by length, descending
            # Case-insensitive match: if the parsed cultivar is a substring of a known one, or vice-versa,
            # or if they are equal ignoring case.
            # We prioritize matching the start of the string for multi-word known cultivars.
            if re.match(rf'^{re.escape(known)}\\b', cultivar, re.IGNORECASE):
                final_cultivar = known # Use casing from KNOWN_CULTIVARS
                standardized = True
                break
            elif re.match(rf'^{re.escape(cultivar)}\\b', known, re.IGNORECASE): # Parsed cultivar is start of a known one
                final_cultivar = known
                standardized = True
                break
        if not standardized:
            # If no direct match, check if any part of the cultivar (if multi-word) is a known cultivar
            # This handles cases like "Pea Spearmint" where "Pea" is known.
            cultivar_parts = cultivar.split()
            best_match_from_parts = ""
            for part in cultivar_parts:
                for known_single in KNOWN_CULTIVARS:
                    if part.lower() == known_single.lower():
                        if len(known_single) > len(best_match_from_parts): # Prefer longer match if multiple parts match
                            best_match_from_parts = known_single
            
            if best_match_from_parts:
                final_cultivar = best_match_from_parts
                # Attempt to reconstruct variety if we took a part as cultivar
                # This is a simple heuristic
                if final_cultivar.lower() in cultivar.lower():
                    try:
                        idx = cultivar.lower().find(final_cultivar.lower())
                        temp_variety = cultivar[:idx].strip() + " " + cultivar[idx+len(final_cultivar):].strip()
                        plant_variety = temp_variety.strip() if temp_variety.strip() else plant_variety # Keep original if new is empty
                    except: # Keep original plant_variety on error
                        pass 
                standardized = True # Considered standardized as we matched a part to a known cultivar
            else:
                final_cultivar = cultivar # Use the parsed one as is
                logger.warning(f"Cultivar '{final_cultivar}' from title '{title_string}' (processed: '{processed_title}') not found in KNOWN_CULTIVARS. Consider updating known_cultivars.csv.")
    else: # cultivar was N/A or empty initially
        final_cultivar = "N/A"

    # Ensure plant_variety is not same as cultivar if cultivar was identified
    if final_cultivar != "N/A" and plant_variety.lower().strip() == final_cultivar.lower().strip():
        plant_variety = "N/A"
    if not plant_variety: plant_variety = "N/A"
    if not final_cultivar: final_cultivar = "N/A"

    return {"cultivar": final_cultivar, "plant_variety": plant_variety}

def parse_weight_from_string(text_string):
    if not text_string:
        return None
    TO_KG = {
        'grams': 0.001, 'gram': 0.001, 'g': 0.001,
        'kilos': 1.0, 'kilo': 1.0, 'kilograms': 1.0, 'kilogram': 1.0, 'kg': 1.0,
        'pounds': 0.45359237, 'pound': 0.45359237, 'lbs': 0.45359237, 'lb': 0.45359237,
        'oz': 0.0283495231, 'ounce': 0.0283495231
    }
    pattern = re.compile(r"(\d+\.?\d*)\s*(" + "|".join(TO_KG.keys()) + r")", re.IGNORECASE)
    match = pattern.search(text_string)
    if match:
        value_str, unit_str = match.group(1), match.group(2).lower()
        try:
            value = float(value_str)
            return {'value': value, 'unit': unit_str, 'weight_kg': round(value * TO_KG[unit_str], 6)}
        except ValueError:
            logger.warning(f"Could not convert value '{value_str}' for weight parsing in '{text_string}'")
    return None

def extract_price_from_text(text):
    if not text:
        return 0.0
    match = re.search(r'\$?\s*(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2}|\d+)', text)
    if match:
        price_str = match.group(1).replace(',', '')
        try:
            return float(price_str)
        except ValueError:
            return 0.0
    return 0.0

def save_products_to_json(data_to_save, supplier_name, base_filename_prefix="products"):
    if not data_to_save.get("data"):
        logger.warning("No product data to save.")
        return
    try:
        os.makedirs(SHARED_OUTPUT_DIR, exist_ok=True)
    except OSError as e:
        logger.error(f"Error creating directory {SHARED_OUTPUT_DIR}: {e}. Please check permissions.", exc_info=True)
        return
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{supplier_name}_{base_filename_prefix}_{timestamp_str}.json"
    output_filename = os.path.join(SHARED_OUTPUT_DIR, filename)
    try:
        with open(output_filename, 'w', encoding='utf-8') as output_file:
            json.dump(data_to_save, output_file, ensure_ascii=False, indent=4)
        os.chmod(output_filename, 0o664)
        logger.info(f"Data saved to {output_filename}")
    except IOError as e:
        logger.error(f"Error writing to file {output_filename}: {e}", exc_info=True)
    except OSError as e:
        logger.error(f"Error setting permissions for {output_filename}: {e}", exc_info=True)

# --- Placeholder Scraper Functions (to be adapted from sprouting_scraper.py) ---

def scrape_product_details(page, product_url):
    logger.info(f"Scraping product details from: {product_url}")
    product_data = {
        'url': product_url, # Store original URL for reference
        'is_in_stock': False,
        'variations': [],
        'scrape_error': "" # Initialize as empty string
    }
    current_page_effective_url = product_url # Fallback if goto fails early

    def _append_error(new_error_message):
        if product_data['scrape_error']:
            product_data['scrape_error'] += f"; {new_error_message}"
        else:
            product_data['scrape_error'] = new_error_message

    try:
        page.goto(product_url, timeout=90000, wait_until="load")
        page.wait_for_timeout(3000) # Extra pause for JS after load
        current_page_effective_url = page.url # Get the final URL after redirects
        logger.info(f"Original URL: {product_url}, Effective URL after navigation: {current_page_effective_url}")

        # Check for "No Results Found" or similar page errors early
        page_content_for_error_check = page.content()
        no_results_text_1 = "No Results Found"
        no_results_text_2 = "The page you requested could not be found"
        
        if no_results_text_1 in page_content_for_error_check or \
           no_results_text_2 in page_content_for_error_check:
            logger.warning(f"Product page indicates 'No Results Found' or similar for URL: {current_page_effective_url}")
            _append_error("Product page not found (No Results Found / Page Could Not Be Found)")
            product_data['is_in_stock'] = False
            product_data['variations'] = [] # Ensure variations is empty
            product_data['effective_url'] = current_page_effective_url # Store effective URL before early return
            return product_data # Return early

        cookie_banner_accept_button = page.locator('div#cmplz-cookiebanner-container button.cmplz-btn.cmplz-accept')
        if cookie_banner_accept_button.count() > 0:
            try:
                logger.info(f"Cookie banner accept button found on {current_page_effective_url}. Attempting to click.")
                cookie_banner_accept_button.click(timeout=10000) # Increased timeout for click
                logger.info(f"Clicked cookie banner accept button on {current_page_effective_url}.")
                page.wait_for_timeout(2000) # Wait for banner to potentially disappear
            except PlaywrightTimeoutError:
                logger.warning(f"Timeout trying to click cookie banner on {current_page_effective_url}. It might be unclickable or already handled.")
            except Exception as e:
                logger.warning(f"Error clicking cookie banner on {current_page_effective_url}: {e}")
        else:
            logger.debug(f"No cookie banner accept button found on {current_page_effective_url}.")

        variations_form_selector = 'form.variations_form.cart[data-product_variations]'
        variations_json_string = None
        try:
            variations_json_string = page.locator(variations_form_selector).get_attribute('data-product_variations', timeout=60000)
        except PlaywrightTimeoutError:
            logger.warning(f"Timeout waiting for variations form '{variations_form_selector}' on {current_page_effective_url}.")
            # This path will lead to the 'variations_json_string is None' block below

        if variations_json_string:
            try:
                variations_list_json = json.loads(variations_json_string)
                if not variations_list_json: # Handles case of empty list in JSON data
                    logger.warning(f"Empty variations list from JSON on {current_page_effective_url}")
                    _append_error("Empty variations JSON.")
                
                product_overall_in_stock = False
                if not product_data['variations'] and variations_list_json is not None: 
                    logger.warning(f"Variations JSON processed for {current_page_effective_url}, but no variations were added to product_data.")
                    _append_error("No variations extracted from non-empty JSON.")
                    # Add placeholder if scrape_error wasn't already set to something more specific like "Empty variations JSON"
                    if not any(v['sku'] != 'N/A' for v in product_data['variations']): # Avoid double placeholders
                        product_data['variations'].append({
                            'size': 'default (no variations processed from JSON)', 'price': 0.0, 'is_variation_in_stock': False,
                            'weight_kg': None, 'original_weight_value': None, 'original_weight_unit': None, 'sku': 'N/A'
                        })

            except json.JSONDecodeError as jde:
                logger.error(f"Failed to decode variations JSON for {current_page_effective_url}. Error: {jde}. JSON string snippet: '{str(variations_json_string)[:200]}...'")
                _append_error(f'JSONDecodeError: {str(jde)}')
        else: # variations_json_string is None or empty (e.g., from timeout or missing attribute)
            logger.warning(f"Variations form or 'data-product_variations' attribute not found/empty for {current_page_effective_url}. Might be simple product or page error.")
            _append_error("Variations data JSON not found or empty (simple product or error).")

    except PlaywrightTimeoutError as pte:
        logger.error(f"Playwright timeout during detail extraction for {product_url} (effective: {current_page_effective_url}). Error: {pte}", exc_info=True)
        _append_error(f'Timeout: {str(pte)}')
    except Exception as e:
        logger.exception(f"Error scraping product page {product_url} (effective: {current_page_effective_url}): {e}")
        _append_error(str(e))
    
    # Final check: Ensure variations list has at least one entry, even if it's a placeholder due to an error.
    # This check is skipped if the page was a "No Results Found" type page, as it would have returned early.
    if not product_data['variations'] and product_data.get('scrape_error') != "Product page not found (No Results Found / Page Could Not Be Found)":
        logger.warning(f"No variations populated for {product_url} (effective: {current_page_effective_url}), adding default error variation.")
        error_note_for_placeholder = product_data.get('scrape_error', '') # Should be a string
        if not error_note_for_placeholder: error_note_for_placeholder = 'Unknown issue during scraping or simple product without variations data.'
        
        product_data['variations'].append({
            'size': 'default (error or no data)',
            'price': 0.0,
            'is_variation_in_stock': False,
            'weight_kg': None,
            'original_weight_value': None,
            'original_weight_unit': None,
            'sku': 'N/A',
            'error_note': error_note_for_placeholder
        })
        product_data['is_in_stock'] = False # Ensure overall stock is false if ended up here
    
    product_data['effective_url'] = current_page_effective_url # Add effective URL to data before any return
    return product_data

def scrape_product_list(page, max_pages_override=None):
    """Scrapes product titles, URLs, and basic info from Germina.ca product list pages."""
    basic_products = []
    current_page_num = 1
    
    max_pages = float('inf')
    if TEST_MODE:
        max_pages = 1 # Limit for testing
        logger.info(f"TEST_MODE is True. Limiting product list scrape to {max_pages} page(s).")
    if max_pages_override is not None:
        max_pages = max_pages_override
        logger.info(f"Max pages overridden to: {max_pages}")

    if BASE_SHOP_URL not in page.url:
        logger.info(f"Navigating to initial shop page: {BASE_SHOP_URL}")
        page.goto(BASE_SHOP_URL, timeout=90000, wait_until="domcontentloaded") # Increased timeout
    else:
        logger.info(f"Already on shop page: {page.url}. Ensuring content is loaded.")
        page.wait_for_load_state("domcontentloaded", timeout=90000)

    while current_page_num <= max_pages:
        try:
            logger.info(f"Scraping product list page: {page.url} (Page {current_page_num})")
            page.wait_for_selector('ul.products li.product', timeout=60000, state='visible') # WooCommerce common selector

            product_item_locators = page.locator('ul.products li.product')
            count = product_item_locators.count()
            if count == 0:
                logger.warning(f"No products found on {page.url}. Waiting briefly to check again.")
                page.wait_for_timeout(10000) # Longer wait for slow site
                count = product_item_locators.count()
                if count == 0:
                    logger.warning(f"Still no products on {page.url}. Breaking list scrape for this page.")
                    break
            
            logger.info(f"Found {count} product items on {page.url}.")
            for i in range(count):
                item_locator = product_item_locators.nth(i)
                item_classes = item_locator.get_attribute('class') or ""

                if TARGET_PRODUCT_CATEGORY_CLASS not in item_classes:
                    # For logging purposes, try to get title of skipped item
                    try:
                        skipped_title_loc = item_locator.locator('h2.woocommerce-loop-product__title').first
                        skipped_title = skipped_title_loc.text_content().strip() if skipped_title_loc.count() > 0 else "Unknown title"
                        logger.debug(f"Skipping non-target category product: {skipped_title} on {page.url}")
                    except Exception:
                        logger.debug(f"Skipping non-target category product (title unavailable) on {page.url}")
                    continue

                link_locator = item_locator.locator('a.woocommerce-LoopProduct-link').first
                title_tag = link_locator.locator('h2.woocommerce-loop-product__title').first
                
                title = title_tag.text_content().strip() if title_tag.count() > 0 else ""
                product_url_path = link_locator.get_attribute('href')

                if title and product_url_path:
                    product_url = urljoin(BASE_URL_FOR_PRODUCTS, product_url_path) if not product_url_path.startswith('http') else product_url_path
                    parsed_title_info = parse_cultivar_and_variety_from_title(title)
                    
                    product_data = {
                        'title': title,
                        'cultivar': parsed_title_info['cultivar'],
                        'plant_variety': parsed_title_info['plant_variety'],
                        'url': product_url
                    }
                    basic_products.append(product_data)
                    logger.info(f"Found target product: {title} - URL: {product_url}")
                else:
                    logger.warning(f"Could not find full title/URL for a target product on {page.url}. Classes: {item_classes}")
            
            next_page_locator = page.locator('nav.woocommerce-pagination a.next.page-numbers').first
            if next_page_locator.count() > 0 and current_page_num < max_pages:
                next_page_url_path = next_page_locator.get_attribute('href')
                if next_page_url_path:
                    next_page_url = urljoin(BASE_URL_FOR_PRODUCTS, next_page_url_path)
                    logger.info(f"Navigating to next product list page: {next_page_url}")
                    page.goto(next_page_url, timeout=90000, wait_until="domcontentloaded")
                    time.sleep(5) # Increased politeness delay for slow site
                    current_page_num += 1
                else:
                    logger.info("Next page link found, but no href. Ending list scrape.")
                    break
            else:
                logger.info("No next page link or max pages reached. Ending product list scrape.")
                break
        except PlaywrightTimeoutError as e:
            logger.error(f"Timeout on product list page {page.url}: {e}. Attempting to continue if possible or break.", exc_info=True)
            break # Break on timeout for now
        except Exception as e:
            logger.exception(f"Error on product list page {page.url}: {e}. Stopping list scrape.")
            break
    return basic_products

# --- Main Execution --- 

def main_sync():
    setup_logging()

    overall_start_time = time.time()
    logger.info("Starting Germina.ca scraper (main_sync). HEADLESS=%s, TEST_MODE=%s", HEADLESS, TEST_MODE)

    all_scraped_product_details = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS) 
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
            java_script_enabled=True,
            accept_downloads=False,
            # Consider viewport if page layout is sensitive, increased timeouts for slow site
            # viewport={'width': 1920, 'height': 1080}
        )
        # Set default timeout for actions within the context, if page-specific ones aren't enough
        context.set_default_timeout(90000) # 90 seconds default for actions
        page = context.new_page()

        try:
            # --- Product List Scraping ---
            logger.info(f"Starting product list scraping from: {BASE_SHOP_URL}")
            basic_target_products = scrape_product_list(page) # Max pages handled by TEST_MODE inside function

            # --- Product Detail Scraping ---
            if basic_target_products:
                logger.info(f"Found {len(basic_target_products)} target products. Scraping details...")
                
                products_to_scrape_details_for = basic_target_products
                if TEST_MODE:
                    products_to_scrape_details_for = basic_target_products[:10] # Limit detail scraping in test mode
                    logger.info(f"TEST_MODE: Will scrape details for {len(products_to_scrape_details_for)} products.")

                for i, basic_product_info in enumerate(products_to_scrape_details_for):
                    logger.info(f"Processing product {i+1}/{len(products_to_scrape_details_for)}: {basic_product_info['title']}")
                    time.sleep(3) # Politeness delay

                    detailed_info = scrape_product_details(page, basic_product_info['url'])
                    
                    # Check if the product should be skipped due to "Page Not Found" type errors
                    if detailed_info.get('scrape_error') and "Product page not found (No Results Found / Page Could Not Be Found)" in detailed_info['scrape_error']:
                        logger.info(f"Skipping product '{basic_product_info['title']}' (URL: {basic_product_info['url']}) as its page was not found or indicated no results.")
                        continue # Skip adding this product to the list
                    
                    final_product_data = {
                        'title': basic_product_info['title'],
                        'cultivar': basic_product_info['cultivar'],
                        'plant_variety': basic_product_info['plant_variety'],
                        'url': detailed_info['url'],
                        'is_in_stock': detailed_info['is_in_stock'],
                        'variations': detailed_info['variations']
                    }
                    if detailed_info.get('scrape_error'):
                        final_product_data['scrape_error'] = detailed_info['scrape_error']
                    all_scraped_product_details.append(final_product_data)
            else:
                logger.info("No target products found from list pages.")

            core_scrape_duration_seconds = round(time.time() - overall_start_time, 2)
            if all_scraped_product_details:
                output_data = {
                    "timestamp": datetime.now().isoformat(),
                    "scrape_duration_seconds": core_scrape_duration_seconds,
                    "source_site": BASE_URL_FOR_PRODUCTS,
                    "product_count": len(all_scraped_product_details),
                    "data": all_scraped_product_details
                }
                save_products_to_json(output_data, SUPPLIER_NAME, base_filename_prefix="organic_seeds")
            else:
                logger.info("No products were scraped in detail.")

        except PlaywrightTimeoutError as e:
            logger.critical(f"Playwright timeout in main_sync: {e}", exc_info=True)
        except Exception as e:
            logger.critical(f"Unexpected error in main_sync: {e}", exc_info=True)
        finally:
            logger.info("Closing browser.")
            if 'browser' in locals() and browser.is_connected():
                 browser.close()
            
            overall_duration_seconds = round(time.time() - overall_start_time, 2)
            logger.info(f"Germina scraper finished. Total duration: {overall_duration_seconds} seconds.")
    
if __name__ == "__main__":
    main_sync() 