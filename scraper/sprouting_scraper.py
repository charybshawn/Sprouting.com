#!/usr/bin/env python3
import os
import csv
import time
import json
import re # Added for regex price parsing
from urllib.parse import urljoin
from datetime import datetime
import logging
import logging.handlers # For RotatingFileHandler
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

base_shop_url = "https://sprouting.com/shop/"
SHARED_OUTPUT_DIR = "./scraper_data/json_files/" # Define the shared output directory
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "scraper.log")
HEADLESS = True
TEST_MODE = False # Set to True for testing, False for production (full scrape)

# Setup Logger
logger = logging.getLogger("SproutingScraper")
logger.setLevel(logging.INFO) # Set default logging level

def setup_logging():
    """Configures logging to console and rotating file.
    Call this once at the beginning of the script.
    """
    # Create log directory if it doesn't exist
    if not os.path.exists(LOG_DIR):
        try:
            os.makedirs(LOG_DIR)
        except OSError as e:
            print(f"Error creating log directory {LOG_DIR}: {e}") # Use print if logger not set up
            # Potentially fall back to basicConfig or console only if dir creation fails
            logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
            return

    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(message)s')

    # Rotating File Handler
    # Rotates logs at 5MB, keeps 5 backup logs
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'
        )
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Error setting up file logger: {e}")


    # Console Handler (optional, but good for seeing logs during dev/manual runs)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)

    logger.info("Logging configured. Saving logs to: %s", LOG_FILE)


def parse_weight_from_string(text_string):
    """
    Parses weight information (value and unit) from a string and converts to kilograms.
    Handles grams, g, kilograms, kilo, kg, pounds, pound, lbs, lb, oz, ounce.
    Returns a dictionary with 'value', 'unit', and 'weight_kg' or None if no match.
    """
    if not text_string:
        return None

    # Define conversion factors to kilograms
    TO_KG = {
        'grams': 0.001, 'gram': 0.001, 'g': 0.001,
        'kilos': 1.0, 'kilo': 1.0, 'kilograms': 1.0, 'kilogram': 1.0, 'kg': 1.0,
        'pounds': 0.45359237, 'pound': 0.45359237, 'lbs': 0.45359237, 'lb': 0.45359237,
        'oz': 0.0283495231, 'ounce': 0.0283495231
    }

    # Regex to capture value and unit
    pattern = re.compile(r"(\d+\.?\d*)\s*(" + "|".join(TO_KG.keys()) + r")", re.IGNORECASE)
    match = pattern.search(text_string)

    if match:
        value_str = match.group(1)
        unit_str = match.group(2).lower()
        
        try:
            value = float(value_str)
            weight_kg = value * TO_KG[unit_str]
            return {
                'value': value,
                'unit': unit_str,
                'weight_kg': round(weight_kg, 6) 
            }
        except ValueError:
            # This case should ideally not be reached if regex matches a number
            logger.warning(f"Could not convert value '{value_str}' to float for weight parsing in '{text_string}'")
            return None
    return None

def extract_price_from_text(text):
    if not text:
        return 0.0
    # Regex to find numbers like $16.09, 1,150.10, 231.16
    match = re.search(r'\$?\s*(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2}|\d+)', text)
    if match:
        price_str = match.group(1).replace(',', '')
        try:
            return float(price_str)
        except ValueError:
            return 0.0
    return 0.0

def scrape_product_details(page, product_url):
    """
    Scrapes detailed product information from its individual page,
    including variations, pricing, and definitive stock status.

    Args:
        page: The Playwright page object (reused for efficiency).
        product_url: The URL of the product page to scrape.

    Returns:
        A dictionary containing detailed product information:
        {
            'url': product_url,
            'is_in_stock': True/False, # Overall product stock status
            'variations': [
                {'size': '125g', 'price': 5.99, 'is_variation_in_stock': True},
                # ... more variations
            ]
        }
        Returns None if the page cannot be scraped or essential data is missing.
    """
    logger.info(f"Scraping product details from: {product_url}")
    try:
        page.goto(product_url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_selector('div.product', timeout=30000) # Wait for main product container

        product_data = {
            'url': product_url,
            'is_in_stock': False, # Default to False
            'variations': []
        }

        # Determine product type (simple or grouped)
        product_div = page.locator('div.product').first
        product_classes = product_div.get_attribute('class') or ""

        if "product-type-grouped" in product_classes:
            logger.info(f"Product type: Grouped - {product_url}")
            form_locator = page.locator('form.cart.grouped_form')
            if form_locator.count() == 0:
                logger.warning(f"No grouped form found for {product_url}. Assuming out of stock or different layout.")
                # Try to find a general out-of-stock message for the whole page if form is missing
                if page.locator('p.stock.out-of-stock:visible, div.woocommerce-info:has-text("Out of stock"):visible').count() > 0:
                    logger.info(f"General out-of-stock message found on grouped product page {product_url} without form.")
                    product_data['is_in_stock'] = False
                return product_data # Return with default out-of-stock if no form

            variation_rows = form_locator.locator('table.woocommerce-grouped-product-list tbody tr.woocommerce-grouped-product-list-item')
            num_variations_found = variation_rows.count()
            logger.info(f"Found {num_variations_found} potential variations for grouped product {product_url}")

            any_variation_in_stock_overall = False
            for i in range(num_variations_found):
                logger.debug(f"    Processing variation {i+1}/{num_variations_found} for {product_url}...")
                row = variation_rows.nth(i)
                
                size = ""
                price = 0.0
                is_this_variation_in_stock = False

                # --- Extract Size and Price from Label Cell ---
                label_cell_locator = row.locator('td.woocommerce-grouped-product-list-item__label')
                if label_cell_locator.count() > 0:
                    # Get size from the <label> text
                    size_label_actual_locator = label_cell_locator.locator('label').first
                    if size_label_actual_locator.count() > 0:
                        size = size_label_actual_locator.text_content(timeout=5000) or ""
                        size = size.strip()
                        logger.debug(f"        Size (from label): '{size}'")
                    else:
                        logger.warning(f"        Warning: <label> inside label cell not found for variation {i+1}. Full cell text: '{label_cell_locator.text_content(timeout=2000)}'")
                        size = label_cell_locator.text_content(timeout=2000).split('\n')[0].strip() # Fallback to first line of cell

                    # Get price from the same label cell (new structure based on HTML snippet)
                    price_amount_locator = label_cell_locator.locator('span.wholesale_price_container ins span.woocommerce-Price-amount.amount')
                    if price_amount_locator.count() > 0:
                        price_text_content = price_amount_locator.first.text_content(timeout=5000)
                        price = extract_price_from_text(price_text_content)
                        logger.debug(f"        Price (from label cell's .amount): '{price}' (raw: '{price_text_content}')")
                    else: # Fallback if specific wholesale structure not found, try to get any .amount
                        fallback_price_locator = label_cell_locator.locator('span.woocommerce-Price-amount.amount').first
                        if fallback_price_locator.count() > 0:
                            price_text_content = fallback_price_locator.text_content(timeout=5000)
                            price = extract_price_from_text(price_text_content)
                            logger.debug(f"        Price (from label cell's fallback .amount): '{price}' (raw: '{price_text_content}')")
                        else:
                            logger.warning(f"        Warning: Price amount locator not found in label cell for variation {i+1}. Cell text: '{label_cell_locator.text_content(timeout=2000)}'")
                else:
                    logger.warning(f"        Warning: Label cell not found for variation {i+1}")


                # --- Determine Stock Status for this variation ---
                row_classes = row.get_attribute('class') or ""
                quantity_cell_locator = row.locator('td.woocommerce-grouped-product-list-item__quantity')
                qty_input_locator = quantity_cell_locator.locator('input.qty[type="number"]')
                view_button_locator = quantity_cell_locator.locator('a.button:has-text("View")')

                if "instock" in row_classes and qty_input_locator.count() > 0 and qty_input_locator.is_enabled(timeout=1000):
                    is_this_variation_in_stock = True
                    logger.debug(f"        Variation {i+1} determined IN STOCK (row class 'instock' and qty input present/enabled).")
                elif qty_input_locator.count() > 0 and qty_input_locator.is_enabled(timeout=1000):
                    # If no 'instock' class, but qty input is there, check for no 'outofstock' class on row
                    if "outofstock" not in row_classes:
                        is_this_variation_in_stock = True
                        logger.debug(f"        Variation {i+1} determined IN STOCK (qty input present/enabled, no 'outofstock' row class).")
                    else:
                        is_this_variation_in_stock = False
                        logger.debug(f"        Variation {i+1} determined OUT OF STOCK (qty input present but row class 'outofstock').")
                elif "outofstock" in row_classes:
                    is_this_variation_in_stock = False
                    logger.debug(f"        Variation {i+1} determined OUT OF STOCK (row class 'outofstock').")
                elif view_button_locator.count() > 0:
                    is_this_variation_in_stock = False
                    logger.debug(f"        Variation {i+1} determined OUT OF STOCK ('View' button found instead of qty input).")
                else:
                    is_this_variation_in_stock = False # Default to OOS if unclear
                    logger.warning(f"        Warning: Stock status for variation {i+1} unclear, defaulting to OUT OF STOCK. QtyInputCount: {qty_input_locator.count()}, ViewButtonCount: {view_button_locator.count()}, RowClasses: '{row_classes}'")
                
                if not size: # Fallback if size still empty
                    size = f"Unknown Variation {i+1}"
                    logger.warning(f"        Using placeholder size: '{size}'")
                
                parsed_weight_info = parse_weight_from_string(size)

                variation_data = {
                    'size': size,
                    'price': price,
                    'is_variation_in_stock': is_this_variation_in_stock,
                    'weight_kg': parsed_weight_info['weight_kg'] if parsed_weight_info else None,
                    'original_weight_value': parsed_weight_info['value'] if parsed_weight_info else None,
                    'original_weight_unit': parsed_weight_info['unit'] if parsed_weight_info else None,
                }
                product_data['variations'].append(variation_data)
                
                if is_this_variation_in_stock:
                    any_variation_in_stock_overall = True
                
                logger.debug(f"    Finished processing variation {i+1}: Size='{size}', Price='{price}', InStock={is_this_variation_in_stock}")

            product_data['is_in_stock'] = any_variation_in_stock_overall
            if not any_variation_in_stock_overall and num_variations_found > 0 :
                logger.info(f"All {num_variations_found} variations for {product_url} appear out of stock.")
            elif num_variations_found == 0:
                 logger.warning(f"No variations found in the table for grouped product {product_url}. Assuming out of stock based on table content.")
                 product_data['is_in_stock'] = False # No variations means nothing to buy

        elif "product-type-simple" in product_classes or "product-type-variable" in product_classes: # Handle simple and variable products
            product_type = "Simple" if "product-type-simple" in product_classes else "Variable"
            logger.info(f"Product type: {product_type} - {product_url}")

            # Common out-of-stock messages
            general_out_of_stock_message = page.locator('p.stock.out-of-stock:visible, div.stock.out-of-stock:visible, form.cart p.stock.out-of-stock:visible, .woocommerce-variation-availability p.stock.out-of-stock:visible').first
            
            # Add to cart button
            add_to_cart_button = page.locator('button.single_add_to_cart_button:not([disabled], .disabled):visible').first
            
            is_available = False
            price_str_simple_var = "0.00" # Use a different variable name
            current_price_simple_var = 0.0
            size_description = "default" # Default for simple products

            if "product-type-variable" in product_classes:
                # For variable products, variations are often loaded dynamically or present in a <form class="variations_form cart">
                variations_form = page.locator('form.variations_form.cart')
                if variations_form.count() > 0:
                    # Check if any variation is available
                    # This might involve selecting options to see if an "add to cart" becomes available
                    # For now, we check if the form itself indicates availability or if there's an add to cart button
                    
                    # Attempt to find variation data from the 'data-product_variations' attribute
                    form_data_variations = variations_form.get_attribute('data-product_variations')
                    if form_data_variations:
                        try:
                            variations_json = json.loads(form_data_variations)
                            for var_json in variations_json:
                                var_attributes = var_json.get('attributes', {})
                                var_size = ", ".join(var_attributes.values()) if var_attributes else 'default'
                                var_price_html = var_json.get('price_html', '') # Price might be in HTML
                                var_price_from_json = float(var_json.get('display_price', 0))
                                
                                # Price from html might be more accurate if available
                                current_price_simple_var = var_price_from_json 
                                # Simplified price extraction from HTML for variable, as it's complex
                                # Preferring display_price from JSON for now.

                                var_is_in_stock_json = var_json.get('is_in_stock', False)
                                
                                parsed_weight_info_var = parse_weight_from_string(var_size)

                                product_data['variations'].append({
                                    'size': var_size,
                                    'price': current_price_simple_var,
                                    'is_variation_in_stock': var_is_in_stock_json,
                                    'weight_kg': parsed_weight_info_var['weight_kg'] if parsed_weight_info_var else None,
                                    'original_weight_value': parsed_weight_info_var['value'] if parsed_weight_info_var else None,
                                    'original_weight_unit': parsed_weight_info_var['unit'] if parsed_weight_info_var else None,
                                })
                                if var_is_in_stock_json:
                                    is_available = True
                                logger.debug(f"    Variable Variation (JSON): Size='{var_size}', Price='{current_price_simple_var}', InStock={var_is_in_stock_json}")
                        except json.JSONDecodeError:
                            logger.error(f"Could not parse data-product_variations for {product_url}", exc_info=True)
                    
                    # Fallback if JSON parsing fails or not present, check for visible add to cart / out of stock messages
                    if not product_data['variations']: # If JSON didn't yield variations
                        if add_to_cart_button.count() > 0:
                            is_available = True
                            # Try to get a general price if no variations were parsed
                            price_simple_locator = page.locator('p.price span.woocommerce-Price-amount.amount bdi, .woocommerce-variation-price span.woocommerce-Price-amount.amount bdi').first
                            if price_simple_locator.count() > 0:
                                price_text = price_simple_locator.text_content(timeout=5000)
                                if price_text:
                                    price_str_simple_var = price_text.replace('$', '').replace(',', '').strip()
                            
                            temp_size_for_parsing = 'default (check options)'
                            parsed_weight_info_fallback = parse_weight_from_string(temp_size_for_parsing)

                            product_data['variations'].append({
                                'size': temp_size_for_parsing, # Use the actual size string
                                'price': float(price_str_simple_var) if price_str_simple_var and price_str_simple_var.replace('.', '', 1).isdigit() else 0.0,
                                'is_variation_in_stock': True,
                                'weight_kg': parsed_weight_info_fallback['weight_kg'] if parsed_weight_info_fallback else None,
                                'original_weight_value': parsed_weight_info_fallback['value'] if parsed_weight_info_fallback else None,
                                'original_weight_unit': parsed_weight_info_fallback['unit'] if parsed_weight_info_fallback else None,
                            })
                            logger.info(f"    Variable product {product_url} seems available, add to cart button visible. Price: {price_str_simple_var}")
                        elif general_out_of_stock_message.count() > 0:
                             logger.info(f"    Variable product {product_url} shows general out of stock message.")
                             is_available = False
                             product_data['variations'].append({ # Add a default OOS variation
                                'size': 'default (out of stock)',
                                'price': 0.0,
                                'is_variation_in_stock': False,
                                'weight_kg': None,
                                'original_weight_value': None,
                                'original_weight_unit': None,
                            })
                        else:
                            logger.warning(f"    Variable product {product_url} - stock status unclear, no variations JSON, no clear OOS/Add to Cart button. Assuming OOS.")
                            is_available = False # Default to OOS if unclear
                            product_data['variations'].append({
                                'size': 'default (status unclear)',
                                'price': 0.0,
                                'is_variation_in_stock': False,
                                'weight_kg': None,
                                'original_weight_value': None,
                                'original_weight_unit': None,
                            })


                else: # No variations_form found for variable product
                    logger.warning(f"No variations_form found for variable product {product_url}. Checking general availability.")
                    if add_to_cart_button.count() > 0:
                        is_available = True
                    elif general_out_of_stock_message.count() > 0:
                        is_available = False
                    # Get price for simple product logic
                    price_simple_locator = page.locator('p.price span.woocommerce-Price-amount.amount bdi, .woocommerce-variation-price span.woocommerce-Price-amount.amount bdi').first
                    if price_simple_locator.count() > 0:
                        price_text = price_simple_locator.text_content(timeout=5000)
                        if price_text:
                            price_str_simple_var = price_text.replace('$', '').replace(',', '').strip()
                    
                    parsed_weight_info_simple_var_no_form = parse_weight_from_string(size_description)
                    product_data['variations'].append({
                        'size': size_description,
                        'price': float(price_str_simple_var) if price_str_simple_var and price_str_simple_var.replace('.', '', 1).isdigit() else 0.0,
                        'is_variation_in_stock': is_available,
                        'weight_kg': parsed_weight_info_simple_var_no_form['weight_kg'] if parsed_weight_info_simple_var_no_form else None,
                        'original_weight_value': parsed_weight_info_simple_var_no_form['value'] if parsed_weight_info_simple_var_no_form else None,
                        'original_weight_unit': parsed_weight_info_simple_var_no_form['unit'] if parsed_weight_info_simple_var_no_form else None,
                    })
                    logger.info(f"    Stock for {product_type} {product_url} (no variation form): {is_available}, Price: {price_str_simple_var}")

            else: # Simple product specific logic
                if add_to_cart_button.count() > 0:
                    is_available = True
                elif general_out_of_stock_message.count() > 0:
                    is_available = False
                else: # Fallback if neither is clearly present
                    is_available = False # Default to OOS if button isn't clearly there for simple
                    logger.warning(f"    Simple product {product_url} - Add to cart button not found or general OOS message not found. Assuming OOS.")


                price_simple_locator = page.locator('p.price span.woocommerce-Price-amount.amount bdi, div.product-type-simple span.price span.woocommerce-Price-amount.amount bdi').first
                if price_simple_locator.count() > 0:
                    price_text = price_simple_locator.text_content(timeout=5000)
                    if price_text:
                         price_str_simple_var = price_text.replace('$', '').replace(',', '').strip()
                
                parsed_weight_info_simple = parse_weight_from_string(size_description)
                product_data['variations'].append({
                    'size': size_description,
                    'price': float(price_str_simple_var) if price_str_simple_var and price_str_simple_var.replace('.', '', 1).isdigit() else 0.0,
                    'is_variation_in_stock': is_available,
                    'weight_kg': parsed_weight_info_simple['weight_kg'] if parsed_weight_info_simple else None,
                    'original_weight_value': parsed_weight_info_simple['value'] if parsed_weight_info_simple else None,
                    'original_weight_unit': parsed_weight_info_simple['unit'] if parsed_weight_info_simple else None,
                })
                logger.info(f"    Stock for Simple {product_url}: {is_available}, Price: {price_str_simple_var}")

            product_data['is_in_stock'] = is_available
            if not product_data['variations'] and not is_available: # Ensure there's at least one variation entry if OOS
                product_data['variations'].append({
                    'size': 'default (out of stock)',
                    'price': 0.0,
                    'is_variation_in_stock': False,
                    'weight_kg': None,
                    'original_weight_value': None,
                    'original_weight_unit': None,
                })


        else: # Unknown product type or issue
            logger.error(f"Unknown product type or error for {product_url}. Classes: {product_classes}")
            # Check for general out-of-stock messages as a fallback
            if page.locator('p.stock.out-of-stock:visible, div.woocommerce-info:has-text("Out of stock"):visible').count() > 0:
                product_data['is_in_stock'] = False
                logger.info(f"General out-of-stock message found on page {product_url} with unknown type.")
            if not product_data['variations']: # Ensure there's at least one variation entry if OOS
                product_data['variations'].append({
                    'size': 'default (unknown type / out of stock)',
                    'price': 0.0,
                    'is_variation_in_stock': False,
                    'weight_kg': None,
                    'original_weight_value': None,
                    'original_weight_unit': None,
                })


        # Final check: if no variations were added at all, and it's marked in stock, add a default placeholder
        if product_data['is_in_stock'] and not product_data['variations']:
            logger.warning(f"Warning: Product {product_url} marked in_stock but no variations found. Adding a default placeholder variation.")
            product_data['variations'].append({
                'size': 'default (check page)',
                'price': 0.0, # Price unknown
                'is_variation_in_stock': True,
                'weight_kg': None,
                'original_weight_value': None,
                'original_weight_unit': None,
            })
        elif not product_data['is_in_stock'] and not product_data['variations']:
            # If determined OOS and no variations were logged (e.g. early exit), add a placeholder
            product_data['variations'].append({
                'size': 'default (out of stock)',
                'price': 0.0,
                'is_variation_in_stock': False,
                'weight_kg': None,
                'original_weight_value': None,
                'original_weight_unit': None,
            })


        logger.info(f"Finished scraping details for {product_url}. Overall Stock: {product_data['is_in_stock']}, Variations found: {len(product_data['variations'])}")
        return product_data

    except PlaywrightTimeoutError as pte: # Give the exception an alias
        logger.error(f"Playwright timeout during detail extraction for {product_url}. Error: {pte}", exc_info=True)
        return {'url': product_url, 'is_in_stock': False, 'variations': [{'size': 'default (timeout)', 'price': 0.0, 'is_variation_in_stock': False}], 'error': f'Timeout during detail extraction: {str(pte)}'}
    except Exception as e:
        logger.exception(f"Error scraping product page {product_url}: {e}")
        return {'url': product_url, 'is_in_stock': False, 'variations': [{'size': 'default (error)', 'price': 0.0, 'is_variation_in_stock': False}], 'error': str(e)}

def scrape_product_list(page, max_pages_override=None):
    """
    Scrapes product titles and URLs from product list pages.
    It only identifies microgreens. Detailed stock and pricing
    are fetched from individual product pages.

    Args:
        page: The Playwright page object.
        max_pages_override: If provided, overrides the TEST_MODE setting for max pages.

    Returns:
        A list of dictionaries, where each dictionary contains
        'title' and 'url' of a microgreen product.
    """
    basic_products = []
    current_page_num = 1
    base_url_for_products = "https://sprouting.com"

    if TEST_MODE:
        max_pages = 1
        logger.info("TEST_MODE is True. Limiting product list scrape to 1 page.")
    else:
        max_pages = float('inf') # Effectively unlimited for production
        logger.info("TEST_MODE is False. Attempting to scrape all product list pages.")

    if max_pages_override is not None:
        max_pages = max_pages_override
        logger.info(f"Max pages overridden to: {max_pages}")

    if base_shop_url not in page.url:
        logger.info(f"Navigating to initial shop page: {base_shop_url}")
        page.goto(base_shop_url, timeout=60000, wait_until="domcontentloaded")
    else:
        logger.info(f"Already on shop page: {page.url}. Waiting for content.")
        page.wait_for_load_state("domcontentloaded", timeout=60000)
    
    logger.info(f"Waiting for shop page content to load at {page.url}...")
    try:
        page.wait_for_selector('ul.products li.product', timeout=60000) 
        logger.info("Product list detected.")
    except PlaywrightTimeoutError:
        logger.warning(f"Timeout waiting for product list on {page.url}. Trying to proceed anyway after domcontentloaded.")
        # No need for page.wait_for_load_state here again as it was done above or in initial goto

    while current_page_num <= max_pages:
        try:
            logger.info(f"Scraping product list page: {page.url} (Page {current_page_num}/{max_pages})")
            # Ensure products are visible/loaded after potential navigation
            page.wait_for_selector('ul.products li.product', timeout=30000, state='visible')

            product_item_locators = page.locator('li.product')
            count = product_item_locators.count()
            if count == 0:
                logger.warning(f"No products found on page: {page.url}. Checking after a small delay.")
                page.wait_for_timeout(5000) 
                count = product_item_locators.count() # Re-check
                if count == 0:
                    logger.warning(f"Still no products found on page: {page.url} after extra wait. Breaking from list scrape for this page.")
                    break

            logger.info(f"Found {count} product items on {page.url}.")
            for i in range(count):
                item_locator = product_item_locators.nth(i)
                
                item_classes = item_locator.get_attribute('class') or ""
                is_microgreen = "product_cat-microgreen-seeds" in item_classes
                
                if not is_microgreen:
                    # Try to get title for logging skipped item
                    title_for_skip_log_locator = item_locator.locator('a.woocommerce-LoopProduct-link h2.woocommerce-loop-product__title').first
                    title_for_skip_log = title_for_skip_log_locator.text_content().strip() if title_for_skip_log_locator.count() > 0 else "Unknown title"
                    logger.debug(f"Skipping non-microgreen product: {title_for_skip_log} on {page.url}")
                    continue

                link_locator = item_locator.locator('a.woocommerce-LoopProduct-link').first
                title_tag = link_locator.locator('h2.woocommerce-loop-product__title').first
                
                title = ""
                if title_tag.count() > 0:
                    title = title_tag.text_content().strip()
                
                product_url_path = link_locator.get_attribute('href')

                if title and product_url_path:
                    product_url = urljoin(base_url_for_products, product_url_path) if not product_url_path.startswith('http') else product_url_path
                    
                    product_data = {
                        'title': title, 
                        'url': product_url
                        # 'is_microgreen' and 'is_in_stock' from list page are no longer primary
                    }
                    basic_products.append(product_data)
                    logger.info(f"Found microgreen on list: {title} - URL: {product_url}")
                else:
                    item_html_for_log = item_locator.inner_html(timeout=5000) if item_locator.count() > 0 else "Unknown item"
                    logger.warning(f"Could not find full title/URL for a microgreen product on {page.url}. Item HTML (approx): {item_html_for_log[:200]}...")

            next_page_locator = page.locator('nav.woocommerce-pagination a.next.page-numbers').first
            
            if next_page_locator.count() > 0 and current_page_num < max_pages:
                next_page_url_path = next_page_locator.get_attribute('href')
                if next_page_url_path:
                    next_page_url = urljoin(base_url_for_products, next_page_url_path)
                    logger.info(f"Navigating to next product list page: {next_page_url}")
                    page.goto(next_page_url, timeout=60000, wait_until="domcontentloaded")
                    time.sleep(3) # Politeness delay after navigation
                    current_page_num += 1
                else:
                    logger.info("Next page link found, but no href attribute. Ending product list scrape.")
                    break
            else:
                if current_page_num >= max_pages:
                    logger.info("Max pages reached for product list scrape.")
                else:
                    logger.info("No next page link found. Ending product list scrape.")
                break
        except PlaywrightTimeoutError as e:
            logger.error(f"Timeout error on product list page {page.url} (Page {current_page_num}): {e}. Skipping to next.")
            # Attempt to recover by going to the next page if URL is known, or break
            # For simplicity now, we break. More robust recovery could be added.
            break 
        except Exception as e:
            logger.exception(f"An error occurred on product list page {page.url} (Page {current_page_num}): {e}. Stopping list scrape.")
            break # Stop scraping product lists on other errors too
    
    return basic_products

def save_products_to_json(data_to_save, supplier_name, base_filename_prefix="products"):
    """
    Saves data to a JSON file in the SHARED_OUTPUT_DIR
    with a supplier name and timestamp in the filename.

    Args:
        data_to_save: The dictionary containing the data to save.
        supplier_name: A string identifying the supplier (e.g., "sprouting_com").
        base_filename_prefix: A prefix for the filename, defaults to "products".
    """
    if not data_to_save.get("data"): 
        logger.warning("No product data to save.")
        return

    # Ensure the shared output directory exists
    try:
        os.makedirs(SHARED_OUTPUT_DIR, exist_ok=True)
        # Attempt to set permissions more openly if newly created, though umask is usually better
        # os.chmod(SHARED_OUTPUT_DIR, 0o777) # Example, be careful with 777
    except OSError as e:
        logger.error(f"Error creating directory {SHARED_OUTPUT_DIR}: {e}. Please check permissions.", exc_info=True)
        return

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Filename format: supplier_name_base_prefix_YYYYMMDD_HHMMSS.json
    filename = f"{supplier_name}_{base_filename_prefix}_{timestamp_str}.json"
    output_filename = os.path.join(SHARED_OUTPUT_DIR, filename)
    
    try:
        with open(output_filename, 'w', encoding='utf-8') as output_file:
            json.dump(data_to_save, output_file, ensure_ascii=False, indent=4)
        os.chmod(output_filename, 0o664) # Set file permissions: rw-rw-r--
        logger.info(f"Data saved to {output_filename}")
    except IOError as e:
        logger.error(f"Error writing to file {output_filename}: {e}", exc_info=True)
    except OSError as e:
        logger.error(f"Error setting permissions for {output_filename}: {e}", exc_info=True)

def main_sync():
    setup_logging() # Initialize logging configuration
    
    overall_start_time = time.time() # Start timer for the whole main_sync operation
    logger.info("Starting main_sync process.")

    load_dotenv() 

    username = os.environ.get('SPROUTING_USERNAME')
    password = os.environ.get('SPROUTING_PASSWORD')

    # You were setting headless=True, ensure this is what you want for final runs.
    # For debugging, headless=False is often useful.
    # User has set headless=True in their last edit.
    playwright_headless_mode = HEADLESS 
    logger.info(f"Playwright headless mode: {playwright_headless_mode}")


    if not username or not password:
        logger.warning("SPROUTING_USERNAME and SPROUTING_PASSWORD environment variables must be set or present in .env")
        logger.warning("Attempting to scrape without login (public data only).")

    all_scraped_product_details = [] # This will store the final detailed data for all products

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=playwright_headless_mode) 
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
            java_script_enabled=True,
            accept_downloads=False,
            # Consider viewport if page layout is sensitive
            # viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page() # Page for product listings and initial navigation

        error_page_counter = 0
        def save_error_page_content(page_content_to_save, base_filename="error_page"):
            nonlocal error_page_counter # Use nonlocal to modify counter in outer scope
            error_page_counter += 1
            # Save error pages to the log directory for easier cleanup/management
            error_filename = os.path.join(LOG_DIR, f"{base_filename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{error_page_counter}.html")
            try:
                with open(error_filename, "w", encoding="utf-8") as f:
                    f.write(page_content_to_save)
                logger.info(f"Saved error page content to {error_filename} for review.")
            except Exception as e_save_err:
                 logger.error(f"Could not save error page {error_filename}: {e_save_err}", exc_info=True)


        try:
            login_successful = False
            if username and password: 
                logger.info(f"Navigating to login page: https://sprouting.com/my-account/")
                page.goto("https://sprouting.com/my-account/", timeout=60000, wait_until="domcontentloaded")
                logger.info("Login page loaded. Entering credentials.")
                page.fill("input[name='username']", username, timeout=30000)
                page.fill("input[name='password']", password, timeout=30000)
                logger.info("Credentials entered. Clicking login button.")
                
                # Click and then wait for navigation OR specific error messages
                login_button_locator = page.locator("button[name='login']")
                if login_button_locator.count() > 0:
                    login_button_locator.click(timeout=10000) # Short timeout for click itself
                else:
                    logger.error("Login button not found!")
                    raise Exception("Login button not found on /my-account/ page.")

                # Check for immediate errors on the current page OR successful navigation
                try:
                    # Option 1: Successful navigation (priority)
                    # Wait for EITHER shop URL or my-account URL (if errors appear there)
                    logger.info("Waiting for navigation or error message after login click...")
                    page.wait_for_url(lambda url: "sprouting.com/shop/" in url or "sprouting.com/my-account/" in url, timeout=25000)
                    logger.info(f"Landed on URL: {page.url} after login attempt.")

                    if "sprouting.com/shop/" in page.url:
                        # Successfully navigated to shop, now confirm login status
                        body_classes_shop = page.locator('body').get_attribute('class') or ""
                        logout_link_visible_shop = page.locator('a[href*="logout"]:visible, a:has-text("Logout"):visible, a:has-text("Log out"):visible').count() > 0

                        if 'logged-in' in body_classes_shop or logout_link_visible_shop:
                            login_successful = True
                            user_type = 'wholesale_customer' if 'wholesale_customer' in body_classes_shop else 'logged-in'
                            logger.info(f"Login successful! Confirmed on {page.url}. User type: {user_type}")
                        else:
                            logger.warning(f"Redirected to {page.url}, but could not confirm logged-in status (no 'logged-in' class or logout link).")
                            save_error_page_content(page.content(), "error_page_shop_login_check_fail")
                            login_successful = False # Treat as fail if cant confirm

                    elif "sprouting.com/my-account/" in page.url:
                        # Still on my-account, check for errors
                        error_message_selectors = [
                            "ul.woocommerce-error li", 
                            ".woocommerce-notices-wrapper .woocommerce-error",
                            ".woocommerce-message" # General message container
                        ]
                        immediate_login_error_found = False
                        for selector in error_message_selectors:
                            error_elements = page.locator(selector)
                            if error_elements.count() > 0:
                                for i in range(error_elements.count()):
                                    error_text = error_elements.nth(i).text_content().strip().lower()
                                    # Broader error check
                                    if "error" in error_text or "unknown email" in error_text or "incorrect password" in error_text or "the password you entered" in error_text:
                                        logger.error(f"Login Error Found on {page.url}: {error_elements.nth(i).text_content().strip()}")
                                        immediate_login_error_found = True
                                        break
                                if immediate_login_error_found: break
                        
                        if immediate_login_error_found:
                            login_successful = False
                            logger.error("Login failed: Error message displayed on /my-account/ page.")
                            save_error_page_content(page.content(), "error_page_login_immediate_fail_on_myaccount")
                        else:
                            logger.warning("Still on /my-account/ after login attempt, but no clear error message. Assuming login failed.")
                            login_successful = False
                            save_error_page_content(page.content(), "error_page_login_stuck_on_myaccount_no_error")
                    else:
                        # Unexpected URL
                        logger.error(f"Landed on unexpected URL {page.url} after login attempt. Assuming login failed.")
                        login_successful = False
                        save_error_page_content(page.content(), "error_page_login_unexpected_url")

                except PlaywrightTimeoutError:
                    logger.error(f"Timeout waiting for navigation/response after login click. Current URL: {page.url}. Login likely failed.")
                    current_content = ""
                    try: current_content = page.content()
                    except Exception: pass # page might be closed or in bad state
                    save_error_page_content(current_content, "error_page_login_timeout_after_click")
                    login_successful = False

            else: # No username/password
                logger.info("No username/password provided, skipping login.")

            if not login_successful and (username and password): # Only halt if login was attempted and failed
                 logger.critical("Halting script due to login failure or inability to confirm login.")
                 browser.close() # Ensure browser closes if we exit early
                 return 

            # --- Start timer for core scraping operations ---
            core_scrape_start_time = time.time()

            # --- Product List Scraping ---
            logger.info(f"Proceeding to scrape product LISTS. Current page: {page.url}")
            # Navigate to shop page if not already there or if login was skipped/failed but we proceed
            if base_shop_url not in page.url:
                logger.info(f"Navigating to shop page for product listing: {base_shop_url}")
                page.goto(base_shop_url, timeout=60000, wait_until="domcontentloaded")
            else: # Already on shop page
                logger.info("Already on shop page or navigated there. Ensuring content is loaded for product listing.")
                page.wait_for_load_state('domcontentloaded', timeout=60000)
            
            # Get list of product URLs and titles for microgreens
            # Limiting to 1 page of list for testing the detail scraping part.
            # Max pages for product list scraping can be controlled here.
            basic_microgreen_products = scrape_product_list(page, max_pages_override=None) 

            # --- Product Detail Scraping ---
            if basic_microgreen_products:
                logger.info(f"\nFound {len(basic_microgreen_products)} microgreen products from list pages. Now scraping details...")
                # Create a new page for detail scraping to avoid state conflicts if desired,
                # or reuse the existing 'page'. Reusing 'page' is simpler for now.
                # If issues arise, a dedicated detail_page = context.new_page() can be used.
                
                if TEST_MODE:
                    max_detail_pages_to_scrape = 2 # Small number for testing
                    logger.info(f"TEST_MODE is True. Limiting detail scraping to {max_detail_pages_to_scrape} products.")
                    products_to_scrape_details_for = basic_microgreen_products[:max_detail_pages_to_scrape]
                else:
                    products_to_scrape_details_for = basic_microgreen_products # Scrape all found products
                    logger.info(f"TEST_MODE is False. Will scrape details for all {len(products_to_scrape_details_for)} found products.")
                
                # logger.info(f"Will scrape details for up to {max_detail_pages_to_scrape} products (or fewer if less were found).") # This log is now conditional

                for i, basic_product_info in enumerate(products_to_scrape_details_for):
                    logger.info(f"\nProcessing product {i+1}/{len(products_to_scrape_details_for)}: {basic_product_info['title']}")
                    time.sleep(2) # Politeness delay between hitting different product pages

                    detailed_info = scrape_product_details(page, basic_product_info['url'])
                    
                    if detailed_info:
                        # Combine basic info (title) with detailed info
                        final_product_data = {
                            'title': basic_product_info['title'],
                            'url': detailed_info['url'],
                            'is_in_stock': detailed_info['is_in_stock'],
                            'variations': detailed_info['variations']
                        }
                        if 'error' in detailed_info: # Keep error info if present
                            final_product_data['scrape_error'] = detailed_info['error']
                        all_scraped_product_details.append(final_product_data)
                    else:
                        # Fallback if scrape_product_details returns None (should not happen with current return structure)
                        all_scraped_product_details.append({
                            'title': basic_product_info['title'],
                            'url': basic_product_info['url'],
                            'is_in_stock': False,
                            'variations': [{'size':'default (detail scrape failed)', 'price':0.0, 'is_variation_in_stock': False,
                                           'weight_kg': None, 'original_weight_value': None, 'original_weight_unit': None}],
                            'scrape_error': 'Detail scraping function returned None'
                        })
            else:
                logger.info("No microgreen products found from list pages to scrape details for.")

            # --- End timer for core scraping operations ---
            core_scrape_end_time = time.time()
            core_scrape_duration_seconds = round(core_scrape_end_time - core_scrape_start_time, 2)
            logger.info(f"Core scraping (product lists and details) took {core_scrape_duration_seconds} seconds.")

            # --- Save to JSON ---
            if all_scraped_product_details:
                current_timestamp_iso = datetime.now().isoformat() # Use current timestamp for the overall data object
                output_data = {
                    "timestamp": current_timestamp_iso,
                    "scrape_duration_seconds": core_scrape_duration_seconds, # Added duration
                    "source_site": "https://sprouting.com", 
                    "product_count": len(all_scraped_product_details),
                    "data": all_scraped_product_details
                }
                # Pass the supplier_name to save_products_to_json
                save_products_to_json(output_data, supplier_name="sprouting_com", base_filename_prefix="detailed")
            else:
                logger.info("No products were scraped in detail.")

        except PlaywrightTimeoutError as e:
            logger.critical(f"A Playwright timeout occurred in main_sync: {e}", exc_info=True)
            current_content = ""
            try: current_content = page.content()
            except Exception: pass
            save_error_page_content(current_content, "error_page_playwright_timeout_main")
        except Exception as e:
            logger.critical(f"An unexpected error occurred in main_sync: {e}", exc_info=True)
            current_content = ""
            try: current_content = page.content() # Try to get page content if possible
            except Exception: pass
            save_error_page_content(current_content, "error_page_unexpected_main")
        finally:
            logger.info("Closing browser.")
            if 'browser' in locals() and browser.is_connected():
                 browser.close()
            
            overall_end_time = time.time()
            overall_duration_seconds = round(overall_end_time - overall_start_time, 2)
            logger.info(f"main_sync process finished. Total duration: {overall_duration_seconds} seconds.")
    
if __name__ == "__main__":
    main_sync() 