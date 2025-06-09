#!/usr/bin/env python3
import os
import csv
import time
import json
import re 
import random
import argparse
from urllib.parse import urljoin
from datetime import datetime
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from seed_name_parser import parse_with_botanical_field_names
from scraper_utils import (
    setup_logging, retry_on_failure, parse_weight_from_string,
    standardize_size_format, extract_price, save_products_to_json,
    validate_product_data, clean_text, make_absolute_url, is_organic_product,
    calculate_canadian_import_costs, ScraperError, NetworkError
)

"""
# Standardized JSON output format for all scrapers:
{
    "timestamp": "2025-05-27T12:39:07.123456", # ISO format timestamp when scrape completed
    "scrape_duration_seconds": 123.45,         # Time taken to complete the scrape
    "source_site": "https://example.com",      # Base URL of the scraped site
    "currency_code": "CAD",                    # Currency code (CAD, USD, etc.)
    "product_count": 42,                       # Number of products in the data array
    "data": [                                  # Array of product objects
        {
            "title": "Product Name",           # Full product title
            "common_name": "Sunflower",        # Common name (e.g., "Sunflower")
            "cultivar_name": "Black Oil",      # Cultivar name (e.g., "Black Oil") 
            "organic": true,                   # True if product title contains organic indicators
            "url": "https://example.com/product/sunflower", # Product page URL
            "is_in_stock": true,               # Overall product stock status
            "variations": [                    # Array of product variations
                {
                    "size": "100g",            # Size/weight/description of the variation
                    "price": 12.99,            # Price in the currency specified above
                    "is_variation_in_stock": true, # Stock status of this specific variation
                    "weight_kg": 0.1,          # Weight in kg (normalized)
                    "original_weight_value": 100, # Original weight value from label
                    "original_weight_unit": "g", # Original weight unit from label
                    "sku": "SF-100"            # SKU if available, "N/A" if not
                }
            ]
        }
    ]
}
"""

# --- Global Configuration & Constants ---
logger = logging.getLogger("GerminaScraper") # MOVED HERE

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "germina_scraper.log")
# Assuming SHARED_OUTPUT_DIR is where individual scrape JSONs go, e.g., scraper_data/json_files/
SHARED_OUTPUT_DIR = "./scraper_data/json_files/germina_seeds"  # Shared with all scrapers

HEADLESS = True 
TEST_MODE = False 
TARGET_PRODUCT_CATEGORY_CLASS = "product_cat-organic-seeds"
BASE_URL_FOR_PRODUCTS = "https://germina.ca" # For resolving relative product URLs


# Corrected path for CULTIVARS_CSV_FILEPATH
# SCRIPT_DIR is .../Sprouting.com/scraper/
# We want .../Sprouting.com/scraper/scraper_data/known_cultivars.csv
SCRAPER_DATA_ROOT_DIR = os.path.join(SCRIPT_DIR, "scraper_data")
CULTIVARS_CSV_FILEPATH = os.path.join(SCRAPER_DATA_ROOT_DIR, "known_cultivars.csv")

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
        if cultivars_list: # Only log success if there was something to save
            logger.info(f"Saved {len(sorted_cultivars)} known cultivars to {filepath}")
        else:
            logger.info(f"Saved an empty known cultivars CSV to {filepath} (as input list was empty or only contained empty strings).")
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
        logger.error(f"Known cultivars CSV not found at {filepath}. No default cultivars will be loaded. Please create this file, e.g., by running create_cultivars_csv.py.")
        # Attempt to create an empty CSV so the file exists for next time, though it will be empty.
        # This prevents repeated FileNotFoundError if the create_cultivars_csv.py script hasn't been run.
        save_known_cultivars_to_csv(filepath, []) 
        return [] # Return empty list as the file was not found
    except csv.Error as e:
        logger.error(f"CSV formatting error in {filepath}: {e}. Returning empty list of cultivars.")
        return []
    except Exception as e:
        logger.error(f"Error loading known cultivars from {filepath}: {e}. Returning empty list of cultivars.")
        return [] # Return empty list in case of other errors

    # Remove duplicates and empty strings, then sort by length descending for matching
    unique_cultivars = sorted(list(set(c for c in cultivars if c)), key=len, reverse=True)

    # Removed the logic that re-initialized with DEFAULT_CULTIVARS if unique_cultivars was empty.
    # If the CSV is empty or contains no valid cultivars, unique_cultivars will be empty.
    if not unique_cultivars:
        logger.warning(f"Known cultivars CSV ({filepath}) was found but contained no valid cultivar names. Scraper will proceed without known cultivars for matching.")
    
    return unique_cultivars

# Load KNOWN_CULTIVARS at startup
KNOWN_CULTIVARS = load_known_cultivars_from_csv(CULTIVARS_CSV_FILEPATH)

# --- Setup Logger ---
# The logger is already obtained globally. This function will configure its handlers and level.
# logger = logging.getLogger("GerminaScraper") # This line is now at the top
logger.setLevel(logging.INFO) # Setting level here or in setup_logging is fine

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

def standardize_size_format(original_size_text, parsed_weight_info):
    """
    Standardizes the size format to match the format used in damseeds_scraper: "{value} {unit full name}"
    Example: "75 g" becomes "75 grams", "1 kg" becomes "1 kilogram"
    
    Args:
        original_size_text: The original size text
        parsed_weight_info: Dictionary returned by parse_weight_from_string()
        
    Returns:
        Standardized size string or the original if no weight info was parsed
    """
    if not parsed_weight_info:
        return original_size_text
    
    # Get value and unit from parsed weight info
    value = parsed_weight_info['value']
    unit = parsed_weight_info['unit']
    
    # Standardize units to their full names
    unit_mapping = {
        'g': 'grams',
        'gram': 'grams',
        'grams': 'grams',
        'kg': 'kilograms',
        'kilo': 'kilograms',
        'kilos': 'kilograms',
        'kilogram': 'kilograms',
        'kilograms': 'kilograms',
        'lb': 'pounds',
        'lbs': 'pounds',
        'pound': 'pounds',
        'pounds': 'pounds',
        'oz': 'ounces',
        'ounce': 'ounces'
    }
    
    # Get the standardized unit name
    std_unit = unit_mapping.get(unit.lower(), unit)
    
    # If value is a whole number, convert to int for cleaner display
    if value == int(value):
        value = int(value)
    
    # Handle singular form for value of 1
    if value == 1:
        if std_unit.endswith('s'):
            std_unit = std_unit[:-1]  # Remove the 's' for singular
    
    return f"{value} {std_unit}"

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
                else:
                    # Process variations from the JSON data
                    product_overall_in_stock = False
                    
                    for variation in variations_list_json:
                        # Extract variation attributes (combination of attributes like size, color, etc.)
                        attributes = variation.get('attributes', {})
                        attr_desc = []
                        for attr_name, attr_value in attributes.items():
                            # Format: remove 'attribute_' prefix and convert underscores to spaces
                            clean_name = attr_name.replace('attribute_', '').replace('_', ' ')
                            attr_desc.append(f"{clean_name}: {attr_value}")
                        
                        # Create size description from attributes or use fallback
                        size = ", ".join(attr_desc) if attr_desc else "Default"
                        
                        # Extract price
                        price = float(variation.get('display_price', 0.0))
                        
                        # Extract stock status
                        is_in_stock = variation.get('is_in_stock', False)
                        
                        # Extract SKU
                        sku = variation.get('sku', 'N/A')
                        
                        # Parse weight from size description
                        parsed_weight_info = parse_weight_from_string(size)
                        
                        # Skip packet variations
                        if "packet" in size.lower():
                            logger.info(f"    Skipping variation: {size} - labeled as packet")
                            continue
                        
                        standardized_size = standardize_size_format(size, parsed_weight_info)
                        
                        # Calculate Canadian costs (domestic supplier - tax exempt for commercial use)
                        cost_breakdown = calculate_canadian_import_costs(
                            base_price=price,
                            source_currency="CAD",
                            province="BC",
                            weight_kg=parsed_weight_info['weight_kg'] if parsed_weight_info else None,
                            commercial_use=True
                        )
                        
                        # Add the variation to our product data
                        variation_data = {
                            'size': standardized_size,
                            'price': price,
                            'is_variation_in_stock': is_in_stock,
                            'weight_kg': parsed_weight_info['weight_kg'] if parsed_weight_info else None,
                            'original_weight_value': parsed_weight_info['value'] if parsed_weight_info else None,
                            'original_weight_unit': parsed_weight_info['unit'] if parsed_weight_info else None,
                            'sku': sku,
                            'canadian_costs': cost_breakdown
                        }
                        
                        product_data['variations'].append(variation_data)
                        
                        # Update overall stock status
                        if is_in_stock:
                            product_overall_in_stock = True
                            
                    # Set the overall product stock status
                    product_data['is_in_stock'] = product_overall_in_stock
                    
                    logger.info(f"Processed {len(product_data['variations'])} variations from JSON for {current_page_effective_url}")
                
                if not product_data['variations'] and variations_list_json is not None: 
                    logger.warning(f"Variations JSON processed for {current_page_effective_url}, but no variations were added to product_data.")
                    _append_error("No variations extracted from non-empty JSON.")
                    # Add placeholder if scrape_error wasn't already set to something more specific like "Empty variations JSON"
                    if not any(v['sku'] != 'N/A' for v in product_data['variations']): # Avoid double placeholders
                        product_data['variations'].append({
                            'size': 'Default (no variations processed from JSON)',
                            'price': 0.0, 'is_variation_in_stock': False,
                            'weight_kg': None, 'original_weight_value': None, 'original_weight_unit': None, 'sku': 'N/A'
                        })

            except json.JSONDecodeError as jde:
                logger.error(f"Failed to decode variations JSON for {current_page_effective_url}. Error: {jde}. JSON string snippet: '{str(variations_json_string)[:200]}...'")
                _append_error(f'JSONDecodeError: {str(jde)}')
        else: # variations_json_string is None or empty (e.g., from timeout or missing attribute)
            logger.warning(f"Variations form or 'data-product_variations' attribute not found/empty for {current_page_effective_url}. Might be simple product or page error.")
            _append_error("Variations data JSON not found or empty (simple product or error).")
            
            # Try to handle simple products without variations
            try:
                # Look for the price of a simple product
                price_elem = page.locator('p.price span.woocommerce-Price-amount.amount')
                if price_elem.count() > 0:
                    price_text = price_elem.first.text_content()
                    price = extract_price_from_text(price_text)
                    
                    # Check stock status
                    out_of_stock_elem = page.locator('p.stock.out-of-stock')
                    is_in_stock = out_of_stock_elem.count() == 0  # In stock if no out-of-stock message
                    
                    # Get product title for size
                    title_elem = page.locator('h1.product_title')
                    size = title_elem.text_content().strip() if title_elem.count() > 0 else "Default"
                    
                    # Parse weight from size
                    parsed_weight_info = parse_weight_from_string(size)
                    
                    # Skip packet variations
                    if "packet" not in size.lower():
                        standardized_size = standardize_size_format(size, parsed_weight_info)
                        
                        # Calculate Canadian costs (domestic supplier - tax exempt for commercial use)
                        cost_breakdown = calculate_canadian_import_costs(
                            base_price=price,
                            source_currency="CAD",
                            province="BC",
                            weight_kg=parsed_weight_info['weight_kg'] if parsed_weight_info else None,
                            commercial_use=True
                        )
                        
                        # Add simple product variation
                        product_data['variations'].append({
                            'size': standardized_size,
                            'price': price,
                            'is_variation_in_stock': is_in_stock,
                            'weight_kg': parsed_weight_info['weight_kg'] if parsed_weight_info else None,
                            'original_weight_value': parsed_weight_info['value'] if parsed_weight_info else None,
                            'original_weight_unit': parsed_weight_info['unit'] if parsed_weight_info else None,
                            'sku': page.locator('.sku').text_content().strip() if page.locator('.sku').count() > 0 else 'N/A',
                            'canadian_costs': cost_breakdown
                        })
                    else:
                        logger.info(f"    Skipping simple product: {size} - labeled as packet")
                    
                    product_data['is_in_stock'] = is_in_stock
                    logger.info(f"Processed simple product without variations for {current_page_effective_url}")
                else:
                    logger.warning(f"Could not find price for simple product at {current_page_effective_url}")
                    _append_error("No price found for simple product")
            except Exception as simple_e:
                logger.warning(f"Error processing simple product at {current_page_effective_url}: {simple_e}")
                _append_error(f"Simple product processing error: {str(simple_e)}")

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
        
        # Calculate Canadian costs for error case
        cost_breakdown = calculate_canadian_import_costs(
            base_price=0.0,
            source_currency="CAD",
            province="BC",
            weight_kg=None,
            commercial_use=True
        )
        
        product_data['variations'].append({
            'size': 'Default (error or no data)',
            'price': 0.0,
            'is_variation_in_stock': False,
            'weight_kg': None,
            'original_weight_value': None,
            'original_weight_unit': None,
            'sku': 'N/A',
            'error_note': error_note_for_placeholder,
            'canadian_costs': cost_breakdown
        })
        product_data['is_in_stock'] = False # Ensure overall stock is false if ended up here
    
    product_data['effective_url'] = current_page_effective_url # Add effective URL to data before any return
    return product_data

def scrape_product_list(page, max_pages_override=None):
    """
    Scrapes the product list from Germina.ca, handling pagination.
    Returns a list of product URLs and their titles.
    """
    # Use a more specific starting URL that is known to list products
    initial_shop_url = "https://germina.ca/en/product-category/organic-seeds/"
    
    all_products_on_list_pages = []
    page_num = 1
    max_pages = 1 if TEST_MODE else 100 # Default max pages, reduced in test mode
    if max_pages_override is not None:
        max_pages = max_pages_override
        logger.info(f"Max pages overridden to: {max_pages}")

    current_url_to_load = initial_shop_url

    while page_num <= max_pages:
        try:
            if current_url_to_load not in page.url:
                 logger.info(f"Navigating to product list page: {current_url_to_load}")
                 page.goto(current_url_to_load, timeout=90000, wait_until="domcontentloaded")
            else:
                logger.info(f"Already on page: {page.url}. Ensuring content is loaded or reloaded.")
                # Consider reloading if it's the same URL to get fresh content,
                # but be careful about infinite loops if content never appears.
                # For now, let's assume if we are on the URL, we proceed to wait for selector.
                # page.reload(wait_until="domcontentloaded")


            logger.info(f"Scraping product list page: {page.url} (Attempting page {page_num})")
            
            # Wait for product items to be visible
            # The selector 'ul.products li.product' is common for WooCommerce.
            # If this times out, it means the products are not loading on the current page.
            page.wait_for_selector('ul.products li.product', timeout=60000, state='visible') 
            
            products_on_page = page.locator('ul.products li.product').all()
            if not products_on_page:
                logger.info(f"No products found on page {page.url}. This might be the end of pagination or an issue.")
                break

            logger.info(f"Found {len(products_on_page)} products on {page.url}")
            for i in range(len(products_on_page)):
                item_locator = products_on_page[i]
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
                    parsed_title_info = parse_with_botanical_field_names(title)
                    
                    # Skip products that don't match a known cultivar (N/A)
                    if parsed_title_info['common_name'] == "N/A":
                        logger.info(f"Skipping product '{title}' - no matching common name found in known_cultivars.csv")
                        continue
                    
                    product_data = {
                        'title': title,
                        'common_name': parsed_title_info['common_name'],
                        'cultivar_name': parsed_title_info['cultivar_name'],
                        'organic': is_organic_product(title),
                        'url': product_url
                    }
                    all_products_on_list_pages.append(product_data)
                    logger.info(f"Found target product: {title} - URL: {product_url}")
                else:
                    logger.warning(f"Could not find full title/URL for a target product on {page.url}. Classes: {item_classes}")
            
            next_page_locator = page.locator('nav.woocommerce-pagination a.next.page-numbers').first
            if next_page_locator.count() > 0 and page_num < max_pages:
                next_page_url_path = next_page_locator.get_attribute('href')
                if next_page_url_path:
                    next_page_url = urljoin(BASE_URL_FOR_PRODUCTS, next_page_url_path)
                    logger.info(f"Navigating to next product list page: {next_page_url}")
                    page.goto(next_page_url, timeout=90000, wait_until="domcontentloaded")
                    time.sleep(5) # Increased politeness delay for slow site
                    page_num += 1
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
    return all_products_on_list_pages

# --- Main Execution --- 

def main_sync():
    # Configure command-line arguments
    parser = argparse.ArgumentParser(description='Scrape germina.ca for organic seeds data')
    parser.add_argument('--cultivar', type=str, help='Only scrape products matching this cultivar name (case-insensitive)')
    parser.add_argument('--test', action='store_true', help='Enable test mode (limited number of pages)')
    args = parser.parse_args()
    
    # Override test mode if specified in command line
    global TEST_MODE
    if args.test:
        TEST_MODE = True
    
    setup_logging()

    overall_start_time = time.time()
    logger.info("Starting Germina.ca scraper (main_sync). HEADLESS=%s, TEST_MODE=%s", HEADLESS, TEST_MODE)
    if args.cultivar:
        logger.info(f"Filtering for cultivar: {args.cultivar}")

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
            logger.info(f"Starting product list scraping from: {BASE_URL_FOR_PRODUCTS}")
            basic_target_products = scrape_product_list(page) # Max pages handled by TEST_MODE inside function

            # --- Product Detail Scraping ---
            if basic_target_products:
                logger.info(f"Found {len(basic_target_products)} target products. Scraping details...")
                
                # Filter by specific cultivar if requested
                if args.cultivar:
                    filtered_products = []
                    cultivar_pattern = re.compile(re.escape(args.cultivar), re.IGNORECASE)
                    for product in basic_target_products:
                        if cultivar_pattern.search(product['cultivar_name']):
                            filtered_products.append(product)
                            logger.info(f"Including product: {product['title']} (matches cultivar filter)")
                        else:
                            logger.debug(f"Excluding product: {product['title']} (doesn't match cultivar filter)")
                    
                    products_to_scrape_details_for = filtered_products
                    logger.info(f"Filtered to {len(products_to_scrape_details_for)} products matching cultivar: {args.cultivar}")
                elif TEST_MODE:
                    test_count = min(5, len(basic_target_products))
                    products_to_scrape_details_for = random.sample(basic_target_products, test_count)
                    logger.info(f"TEST_MODE: Randomly selected {test_count} products for testing.")
                    for i, product in enumerate(products_to_scrape_details_for):
                        logger.info(f"  Test product {i+1}: {product['title']}")
                else:
                    products_to_scrape_details_for = basic_target_products
                    logger.info(f"Will scrape details for all {len(products_to_scrape_details_for)} products.")

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
                        'common_name': basic_product_info['common_name'],
                        'cultivar_name': basic_product_info['cultivar_name'],
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
                    "currency_code": "CAD",
                    "product_count": len(all_scraped_product_details),
                    "data": all_scraped_product_details
                }
                save_products_to_json(output_data, "germina_ca", base_filename_prefix="organic_seeds")
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