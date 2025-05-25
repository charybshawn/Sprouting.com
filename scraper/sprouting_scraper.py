#!/usr/bin/env python3
import os
import csv
import time
import json
import re # Added for regex price parsing
from urllib.parse import urljoin
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

base_shop_url = "https://sprouting.com/shop/"

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
    print(f"Scraping product details from: {product_url}")
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
            print(f"Product type: Grouped - {product_url}")
            form_locator = page.locator('form.cart.grouped_form')
            if form_locator.count() == 0:
                print(f"No grouped form found for {product_url}. Assuming out of stock or different layout.")
                # Try to find a general out-of-stock message for the whole page if form is missing
                if page.locator('p.stock.out-of-stock:visible, div.woocommerce-info:has-text("Out of stock"):visible').count() > 0:
                    print(f"General out-of-stock message found on grouped product page {product_url} without form.")
                    product_data['is_in_stock'] = False
                return product_data # Return with default out-of-stock if no form

            variation_rows = form_locator.locator('table.woocommerce-grouped-product-list tbody tr.woocommerce-grouped-product-list-item')
            num_variations_found = variation_rows.count()
            print(f"Found {num_variations_found} potential variations for grouped product {product_url}")

            any_variation_in_stock_overall = False
            for i in range(num_variations_found):
                print(f"    Processing variation {i+1}/{num_variations_found} for {product_url}...")
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
                        print(f"        Size (from label): '{size}'")
                    else:
                        print(f"        Warning: <label> inside label cell not found for variation {i+1}. Full cell text: '{label_cell_locator.text_content(timeout=2000)}'")
                        size = label_cell_locator.text_content(timeout=2000).split('\n')[0].strip() # Fallback to first line of cell

                    # Get price from the same label cell (new structure based on HTML snippet)
                    price_amount_locator = label_cell_locator.locator('span.wholesale_price_container ins span.woocommerce-Price-amount.amount')
                    if price_amount_locator.count() > 0:
                        price_text_content = price_amount_locator.first.text_content(timeout=5000)
                        price = extract_price_from_text(price_text_content)
                        print(f"        Price (from label cell's .amount): '{price}' (raw: '{price_text_content}')")
                    else: # Fallback if specific wholesale structure not found, try to get any .amount
                        fallback_price_locator = label_cell_locator.locator('span.woocommerce-Price-amount.amount').first
                        if fallback_price_locator.count() > 0:
                            price_text_content = fallback_price_locator.text_content(timeout=5000)
                            price = extract_price_from_text(price_text_content)
                            print(f"        Price (from label cell's fallback .amount): '{price}' (raw: '{price_text_content}')")
                        else:
                            print(f"        Warning: Price amount locator not found in label cell for variation {i+1}. Cell text: '{label_cell_locator.text_content(timeout=2000)}'")
                else:
                    print(f"        Warning: Label cell not found for variation {i+1}")


                # --- Determine Stock Status for this variation ---
                row_classes = row.get_attribute('class') or ""
                quantity_cell_locator = row.locator('td.woocommerce-grouped-product-list-item__quantity')
                qty_input_locator = quantity_cell_locator.locator('input.qty[type="number"]')
                view_button_locator = quantity_cell_locator.locator('a.button:has-text("View")')

                if "instock" in row_classes and qty_input_locator.count() > 0 and qty_input_locator.is_enabled(timeout=1000):
                    is_this_variation_in_stock = True
                    print(f"        Variation {i+1} determined IN STOCK (row class 'instock' and qty input present/enabled).")
                elif qty_input_locator.count() > 0 and qty_input_locator.is_enabled(timeout=1000):
                    # If no 'instock' class, but qty input is there, check for no 'outofstock' class on row
                    if "outofstock" not in row_classes:
                        is_this_variation_in_stock = True
                        print(f"        Variation {i+1} determined IN STOCK (qty input present/enabled, no 'outofstock' row class).")
                    else:
                        is_this_variation_in_stock = False
                        print(f"        Variation {i+1} determined OUT OF STOCK (qty input present but row class 'outofstock').")
                elif "outofstock" in row_classes:
                    is_this_variation_in_stock = False
                    print(f"        Variation {i+1} determined OUT OF STOCK (row class 'outofstock').")
                elif view_button_locator.count() > 0:
                    is_this_variation_in_stock = False
                    print(f"        Variation {i+1} determined OUT OF STOCK ('View' button found instead of qty input).")
                else:
                    is_this_variation_in_stock = False # Default to OOS if unclear
                    print(f"        Warning: Stock status for variation {i+1} unclear, defaulting to OUT OF STOCK. QtyInputCount: {qty_input_locator.count()}, ViewButtonCount: {view_button_locator.count()}, RowClasses: '{row_classes}'")
                
                if not size: # Fallback if size still empty
                    size = f"Unknown Variation {i+1}"
                    print(f"        Using placeholder size: '{size}'")
                
                variation_data = {
                    'size': size,
                    'price': price,
                    'is_variation_in_stock': is_this_variation_in_stock
                }
                product_data['variations'].append(variation_data)
                
                if is_this_variation_in_stock:
                    any_variation_in_stock_overall = True
                
                print(f"    Finished processing variation {i+1}: Size='{size}', Price='{price}', InStock={is_this_variation_in_stock}")

            product_data['is_in_stock'] = any_variation_in_stock_overall
            if not any_variation_in_stock_overall and num_variations_found > 0 :
                print(f"All {num_variations_found} variations for {product_url} appear out of stock.")
            elif num_variations_found == 0:
                 print(f"No variations found in the table for grouped product {product_url}. Assuming out of stock based on table content.")
                 product_data['is_in_stock'] = False # No variations means nothing to buy

        elif "product-type-simple" in product_classes or "product-type-variable" in product_classes: # Handle simple and variable products
            product_type = "Simple" if "product-type-simple" in product_classes else "Variable"
            print(f"Product type: {product_type} - {product_url}")

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
                                
                                product_data['variations'].append({
                                    'size': var_size,
                                    'price': current_price_simple_var,
                                    'is_variation_in_stock': var_is_in_stock_json
                                })
                                if var_is_in_stock_json:
                                    is_available = True
                                print(f"    Variable Variation (JSON): Size='{var_size}', Price='{current_price_simple_var}', InStock={var_is_in_stock_json}")
                        except json.JSONDecodeError:
                            print(f"Could not parse data-product_variations for {product_url}")
                    
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
                            product_data['variations'].append({
                                'size': 'default (check options)',
                                'price': float(price_str_simple_var) if price_str_simple_var and price_str_simple_var.replace('.', '', 1).isdigit() else 0.0,
                                'is_variation_in_stock': True
                            })
                            print(f"    Variable product {product_url} seems available, add to cart button visible. Price: {price_str_simple_var}")
                        elif general_out_of_stock_message.count() > 0:
                             print(f"    Variable product {product_url} shows general out of stock message.")
                             is_available = False
                             product_data['variations'].append({ # Add a default OOS variation
                                'size': 'default (out of stock)',
                                'price': 0.0,
                                'is_variation_in_stock': False
                            })
                        else:
                            print(f"    Variable product {product_url} - stock status unclear, no variations JSON, no clear OOS/Add to Cart button. Assuming OOS.")
                            is_available = False # Default to OOS if unclear
                            product_data['variations'].append({
                                'size': 'default (status unclear)',
                                'price': 0.0,
                                'is_variation_in_stock': False
                            })


                else: # No variations_form found for variable product
                    print(f"No variations_form found for variable product {product_url}. Checking general availability.")
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
                    
                    product_data['variations'].append({
                        'size': size_description,
                        'price': float(price_str_simple_var) if price_str_simple_var and price_str_simple_var.replace('.', '', 1).isdigit() else 0.0,
                        'is_variation_in_stock': is_available
                    })
                    print(f"    Stock for {product_type} {product_url} (no variation form): {is_available}, Price: {price_str_simple_var}")

            else: # Simple product specific logic
                if add_to_cart_button.count() > 0:
                    is_available = True
                elif general_out_of_stock_message.count() > 0:
                    is_available = False
                else: # Fallback if neither is clearly present
                    is_available = False # Default to OOS if button isn't clearly there for simple
                    print(f"    Simple product {product_url} - Add to cart button not found or general OOS message not found. Assuming OOS.")


                price_simple_locator = page.locator('p.price span.woocommerce-Price-amount.amount bdi, div.product-type-simple span.price span.woocommerce-Price-amount.amount bdi').first
                if price_simple_locator.count() > 0:
                    price_text = price_simple_locator.text_content(timeout=5000)
                    if price_text:
                         price_str_simple_var = price_text.replace('$', '').replace(',', '').strip()
                
                product_data['variations'].append({
                    'size': size_description,
                    'price': float(price_str_simple_var) if price_str_simple_var and price_str_simple_var.replace('.', '', 1).isdigit() else 0.0,
                    'is_variation_in_stock': is_available
                })
                print(f"    Stock for Simple {product_url}: {is_available}, Price: {price_str_simple_var}")

            product_data['is_in_stock'] = is_available
            if not product_data['variations'] and not is_available: # Ensure there's at least one variation entry if OOS
                product_data['variations'].append({
                    'size': 'default (out of stock)',
                    'price': 0.0,
                    'is_variation_in_stock': False
                })


        else: # Unknown product type or issue
            print(f"Unknown product type or error for {product_url}. Classes: {product_classes}")
            # Check for general out-of-stock messages as a fallback
            if page.locator('p.stock.out-of-stock:visible, div.woocommerce-info:has-text("Out of stock"):visible').count() > 0:
                product_data['is_in_stock'] = False
                print(f"General out-of-stock message found on page {product_url} with unknown type.")
            if not product_data['variations']: # Ensure there's at least one variation entry if OOS
                product_data['variations'].append({
                    'size': 'default (unknown type / out of stock)',
                    'price': 0.0,
                    'is_variation_in_stock': False
                })


        # Final check: if no variations were added at all, and it's marked in stock, add a default placeholder
        if product_data['is_in_stock'] and not product_data['variations']:
            print(f"Warning: Product {product_url} marked in_stock but no variations found. Adding a default placeholder variation.")
            product_data['variations'].append({
                'size': 'default (check page)',
                'price': 0.0, # Price unknown
                'is_variation_in_stock': True
            })
        elif not product_data['is_in_stock'] and not product_data['variations']:
            # If determined OOS and no variations were logged (e.g. early exit), add a placeholder
            product_data['variations'].append({
                'size': 'default (out of stock)',
                'price': 0.0,
                'is_variation_in_stock': False
            })


        print(f"Finished scraping details for {product_url}. Overall Stock: {product_data['is_in_stock']}, Variations found: {len(product_data['variations'])}")
        return product_data

    except PlaywrightTimeoutError as pte: # Give the exception an alias
        print(f"Playwright timeout during detail extraction for {product_url}. Error: {pte}. Check logs for last successful step.")
        return {'url': product_url, 'is_in_stock': False, 'variations': [{'size': 'default (timeout)', 'price': 0.0, 'is_variation_in_stock': False}], 'error': f'Timeout during detail extraction: {str(pte)}'}
    except Exception as e:
        print(f"Error scraping product page {product_url}: {e}")
        return {'url': product_url, 'is_in_stock': False, 'variations': [{'size': 'default (error)', 'price': 0.0, 'is_variation_in_stock': False}], 'error': str(e)}

def scrape_product_list(page, max_pages=3):
    """
    Scrapes product titles and URLs from product list pages.
    It only identifies microgreens. Detailed stock and pricing
    are fetched from individual product pages.

    Args:
        page: The Playwright page object.
        max_pages: The maximum number of pages to scrape (for testing).

    Returns:
        A list of dictionaries, where each dictionary contains
        'title' and 'url' of a microgreen product.
    """
    basic_products = []
    current_page_num = 1
    base_url_for_products = "https://sprouting.com"

    if base_shop_url not in page.url:
        print(f"Navigating to initial shop page: {base_shop_url}")
        page.goto(base_shop_url, timeout=60000, wait_until="domcontentloaded")
    else:
        print(f"Already on shop page: {page.url}. Waiting for content.")
        page.wait_for_load_state("domcontentloaded", timeout=60000)
    
    print(f"Waiting for shop page content to load at {page.url}...")
    try:
        page.wait_for_selector('ul.products li.product', timeout=60000) 
        print("Product list detected.")
    except PlaywrightTimeoutError:
        print(f"Timeout waiting for product list on {page.url}. Trying to proceed anyway after domcontentloaded.")
        # No need for page.wait_for_load_state here again as it was done above or in initial goto

    while current_page_num <= max_pages:
        try:
            print(f"Scraping product list page: {page.url} (Page {current_page_num}/{max_pages})")
            # Ensure products are visible/loaded after potential navigation
            page.wait_for_selector('ul.products li.product', timeout=30000, state='visible')

            product_item_locators = page.locator('li.product')
            count = product_item_locators.count()
            if count == 0:
                print(f"No products found on page: {page.url}. Checking after a small delay.")
                page.wait_for_timeout(5000) 
                count = product_item_locators.count() # Re-check
                if count == 0:
                    print(f"Still no products found on page: {page.url} after extra wait. Breaking from list scrape for this page.")
                    break

            print(f"Found {count} product items on {page.url}.")
            for i in range(count):
                item_locator = product_item_locators.nth(i)
                
                item_classes = item_locator.get_attribute('class') or ""
                is_microgreen = "product_cat-microgreen-seeds" in item_classes
                
                if not is_microgreen:
                    # Try to get title for logging skipped item
                    title_for_skip_log_locator = item_locator.locator('a.woocommerce-LoopProduct-link h2.woocommerce-loop-product__title').first
                    title_for_skip_log = title_for_skip_log_locator.text_content().strip() if title_for_skip_log_locator.count() > 0 else "Unknown title"
                    print(f"Skipping non-microgreen product: {title_for_skip_log} on {page.url}")
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
                    print(f"Found microgreen on list: {title} - URL: {product_url}")
                else:
                    item_html_for_log = item_locator.inner_html(timeout=5000) if item_locator.count() > 0 else "Unknown item"
                    print(f"Could not find full title/URL for a microgreen product on {page.url}. Item HTML (approx): {item_html_for_log[:200]}...")

            next_page_locator = page.locator('nav.woocommerce-pagination a.next.page-numbers').first
            
            if next_page_locator.count() > 0 and current_page_num < max_pages:
                next_page_url_path = next_page_locator.get_attribute('href')
                if next_page_url_path:
                    next_page_url = urljoin(base_url_for_products, next_page_url_path)
                    print(f"Navigating to next product list page: {next_page_url}")
                    page.goto(next_page_url, timeout=60000, wait_until="domcontentloaded")
                    time.sleep(3) # Politeness delay after navigation
                    current_page_num += 1
                else:
                    print("Next page link found, but no href attribute. Ending product list scrape.")
                    break
            else:
                if current_page_num >= max_pages:
                    print("Max pages reached for product list scrape.")
                else:
                    print("No next page link found. Ending product list scrape.")
                break
        except PlaywrightTimeoutError as e:
            print(f"Timeout error on product list page {page.url} (Page {current_page_num}): {e}. Skipping to next.")
            # Attempt to recover by going to the next page if URL is known, or break
            # For simplicity now, we break. More robust recovery could be added.
            break 
        except Exception as e:
            print(f"An error occurred on product list page {page.url} (Page {current_page_num}): {e}. Stopping list scrape.")
            break # Stop scraping product lists on other errors too
    
    return basic_products

def save_products_to_json(data_to_save, filename="sprouting_products.json"):
    """
    Saves data (including products and metadata like timestamp) to a JSON file.

    Args:
        data_to_save: The dictionary containing the data to save.
        filename: The name of the JSON file to save.
    """
    if not data_to_save.get("data"): 
        print("No product data to save.")
        return

    # Ensure the output path is within the scraper directory
    scraper_dir = os.path.dirname(os.path.abspath(__file__))
    output_filename = os.path.join(scraper_dir, filename)
    
    with open(output_filename, 'w', encoding='utf-8') as output_file:
        json.dump(data_to_save, output_file, ensure_ascii=False, indent=4)
    print(f"Data saved to {output_filename}")

def main_sync():
    load_dotenv() 

    username = os.environ.get('SPROUTING_USERNAME')
    password = os.environ.get('SPROUTING_PASSWORD')

    # You were setting headless=True, ensure this is what you want for final runs.
    # For debugging, headless=False is often useful.
    # User has set headless=True in their last edit.
    playwright_headless_mode = False 
    print(f"Playwright headless mode: {playwright_headless_mode}")


    if not username or not password:
        print("SPROUTING_USERNAME and SPROUTING_PASSWORD environment variables must be set or present in .env")
        print("Attempting to scrape without login (public data only).")

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
            filename = os.path.join(os.getcwd(), f"{base_filename}_{error_page_counter}.html")
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(page_content_to_save)
                print(f"Saved page content to {filename} for review.")
            except Exception as e_save_err:
                 print(f"Could not save error page {filename}: {e_save_err}")


        try:
            login_successful = False
            if username and password: 
                print(f"Navigating to login page: https://sprouting.com/my-account/")
                page.goto("https://sprouting.com/my-account/", timeout=60000, wait_until="domcontentloaded")
                print("Login page loaded. Entering credentials.")
                page.fill("input[name='username']", username, timeout=30000)
                page.fill("input[name='password']", password, timeout=30000)
                print("Credentials entered. Clicking login button.")
                
                # Click and then wait for navigation OR specific error messages
                login_button_locator = page.locator("button[name='login']")
                if login_button_locator.count() > 0:
                    login_button_locator.click(timeout=10000) # Short timeout for click itself
                else:
                    print("Login button not found!")
                    raise Exception("Login button not found on /my-account/ page.")

                # Check for immediate errors on the current page OR successful navigation
                try:
                    # Option 1: Successful navigation (priority)
                    # Wait for EITHER shop URL or my-account URL (if errors appear there)
                    print("Waiting for navigation or error message after login click...")
                    page.wait_for_url(lambda url: "sprouting.com/shop/" in url or "sprouting.com/my-account/" in url, timeout=25000)
                    print(f"Landed on URL: {page.url} after login attempt.")

                    if "sprouting.com/shop/" in page.url:
                        # Successfully navigated to shop, now confirm login status
                        body_classes_shop = page.locator('body').get_attribute('class') or ""
                        logout_link_visible_shop = page.locator('a[href*="logout"]:visible, a:has-text("Logout"):visible, a:has-text("Log out"):visible').count() > 0

                        if 'logged-in' in body_classes_shop or logout_link_visible_shop:
                            login_successful = True
                            user_type = 'wholesale_customer' if 'wholesale_customer' in body_classes_shop else 'logged-in'
                            print(f"Login successful! Confirmed on {page.url}. User type: {user_type}")
                        else:
                            print(f"Redirected to {page.url}, but could not confirm logged-in status (no 'logged-in' class or logout link).")
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
                                        print(f"Login Error Found on {page.url}: {error_elements.nth(i).text_content().strip()}")
                                        immediate_login_error_found = True
                                        break
                                if immediate_login_error_found: break
                        
                        if immediate_login_error_found:
                            login_successful = False
                            print("Login failed: Error message displayed on /my-account/ page.")
                            save_error_page_content(page.content(), "error_page_login_immediate_fail_on_myaccount")
                        else:
                            print("Still on /my-account/ after login attempt, but no clear error message. Assuming login failed.")
                            login_successful = False
                            save_error_page_content(page.content(), "error_page_login_stuck_on_myaccount_no_error")
                    else:
                        # Unexpected URL
                        print(f"Landed on unexpected URL {page.url} after login attempt. Assuming login failed.")
                        login_successful = False
                        save_error_page_content(page.content(), "error_page_login_unexpected_url")

                except PlaywrightTimeoutError:
                    print(f"Timeout waiting for navigation/response after login click. Current URL: {page.url}. Login likely failed.")
                    current_content = ""
                    try: current_content = page.content()
                    except Exception: pass # page might be closed or in bad state
                    save_error_page_content(current_content, "error_page_login_timeout_after_click")
                    login_successful = False

            else: # No username/password
                print("No username/password provided, skipping login.")

            if not login_successful and (username and password): # Only halt if login was attempted and failed
                 print("Halting script due to login failure or inability to confirm login.")
                 browser.close() # Ensure browser closes if we exit early
                 return 

            # --- Product List Scraping ---
            print(f"Proceeding to scrape product LISTS. Current page: {page.url}")
            # Navigate to shop page if not already there or if login was skipped/failed but we proceed
            if base_shop_url not in page.url:
                print(f"Navigating to shop page for product listing: {base_shop_url}")
                page.goto(base_shop_url, timeout=60000, wait_until="domcontentloaded")
            else: # Already on shop page
                print("Already on shop page or navigated there. Ensuring content is loaded for product listing.")
                page.wait_for_load_state('domcontentloaded', timeout=60000)
            
            # Get list of product URLs and titles for microgreens
            # Limiting to 1 page of list for testing the detail scraping part.
            # Max pages for product list scraping can be controlled here.
            basic_microgreen_products = scrape_product_list(page, max_pages=1) 

            # --- Product Detail Scraping ---
            if basic_microgreen_products:
                print(f"\nFound {len(basic_microgreen_products)} microgreen products from list pages. Now scraping details...")
                # Create a new page for detail scraping to avoid state conflicts if desired,
                # or reuse the existing 'page'. Reusing 'page' is simpler for now.
                # If issues arise, a dedicated detail_page = context.new_page() can be used.
                
                # Limit number of products to scrape details for during testing
                max_detail_pages_to_scrape = 5  # Set to a small number for testing
                products_to_scrape_details_for = basic_microgreen_products[:max_detail_pages_to_scrape]
                print(f"Will scrape details for up to {max_detail_pages_to_scrape} products (or fewer if less were found).")

                for i, basic_product_info in enumerate(products_to_scrape_details_for):
                    print(f"\nProcessing product {i+1}/{len(products_to_scrape_details_for)}: {basic_product_info['title']}")
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
                            'variations': [{'size':'default (detail scrape failed)', 'price':0.0, 'is_variation_in_stock': False}],
                            'scrape_error': 'Detail scraping function returned None'
                        })
            else:
                print("No microgreen products found from list pages to scrape details for.")

            # --- Save to JSON ---
            if all_scraped_product_details:
                timestamp = datetime.now().isoformat()
                output_data = {
                    "timestamp": timestamp,
                    "source_site": "https://sprouting.com", 
                    "product_count": len(all_scraped_product_details),
                    "data": all_scraped_product_details
                }
                save_products_to_json(output_data, "sprouting_products_detailed.json")
            else:
                print("No products were scraped in detail.")

        except PlaywrightTimeoutError as e:
            print(f"A Playwright timeout occurred in main_sync: {e}")
            current_content = ""
            try: current_content = page.content()
            except Exception: pass
            save_error_page_content(current_content, "error_page_playwright_timeout_main")
        except Exception as e:
            print(f"An unexpected error occurred in main_sync: {e}")
            current_content = ""
            try: current_content = page.content() # Try to get page content if possible
            except Exception: pass
            save_error_page_content(current_content, "error_page_unexpected_main")
        finally:
            print("Closing browser.")
            if 'browser' in locals() and browser.is_connected():
                 browser.close()
    
if __name__ == "__main__":
    main_sync() 