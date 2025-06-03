#!/usr/bin/env python3
import os
import json
import time
import re
import urllib.request
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from seed_name_parser import parse_with_botanical_field_names
from scraper_utils import (
    setup_logging, retry_on_failure, parse_weight_from_string,
    standardize_size_format, extract_price, save_products_to_json,
    validate_product_data, clean_text, ScraperError, NetworkError
)

# --- Constants ---
ATOM_FEED_URL = "https://www.damseeds.com/collections/microgreens.atom"
SHARED_OUTPUT_DIR = "./scraper_data/json_files/damm_seeds"  # Shared with sprouting_scraper
SUPPLIER_NAME = "damseeds_com"
HEADLESS = True # Set to False for debugging Playwright interactions
TEST_MODE = False # Set to True to limit scraping for testing

# --- Setup Logger ---
logger = setup_logging("damseeds_scraper")


class SummaryHTMLParser(HTMLParser):
    """
    Parses the HTML content within the <summary> tag of the Atom feed
    to extract image URL and description.
    """
    def __init__(self):
        super().__init__()
        self.image_url = None
        self.description_parts = []
        self.is_in_description_cell = False
        self.is_in_description_paragraph = False
        self.td_colspan_found = False # To identify the correct td for description

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "img" and not self.image_url: # Get first image
            if attributes.get("src") and attributes.get("src") != "#":
                self.image_url = attributes["src"]
            elif attributes.get("src") == "#":
                 self.image_url = None # Explicitly handle placeholder
        
        # Heuristic: description is in <td colspan="2"> then <p>
        if tag == "td":
            if attributes.get("colspan") == "2":
                self.td_colspan_found = True
            else:
                self.td_colspan_found = False # Reset if it's not the one
        
        if tag == "p" and self.td_colspan_found:
            self.is_in_description_paragraph = True
            self.is_in_description_cell = True # Redundant but for clarity
            
    def handle_endtag(self, tag):
        if tag == "p" and self.is_in_description_paragraph:
            self.is_in_description_paragraph = False
            self.td_colspan_found = False # Description paragraph ended, reset
        if tag == "td" and self.is_in_description_cell and not self.is_in_description_paragraph:
            # This condition might need refinement if description cell ends before paragraph
            self.is_in_description_cell = False


    def handle_data(self, data):
        if self.is_in_description_paragraph:
            cleaned_data = data.strip()
            if cleaned_data:
                self.description_parts.append(cleaned_data)
    
    def get_data(self):
        # Join parts, handling <br> tags if they were converted to newlines or need specific processing
        # For now, simple join. Might need to be smarter if <br> are present as entities.
        description = " ".join(self.description_parts).replace('\n', ' ').replace('  ', ' ')
        
        # Further clean-up for multiple spaces that might arise from stripping and joining
        description = re.sub(r'\s+', ' ', description).strip()
        return {"image_url": self.image_url, "description": description}

    def reset(self):
        super().reset()
        self.image_url = None
        self.description_parts = []
        self.is_in_description_cell = False
        self.is_in_description_paragraph = False
        self.td_colspan_found = False


@retry_on_failure(max_attempts=3, delay=2.0)
def fetch_atom_feed(url):
    """Fetches the Atom feed content from the given URL."""
    logger.info(f"Fetching Atom feed from: {url}")
    try:
        with urllib.request.urlopen(url) as response:
            if response.status == 200:
                logger.info("Successfully fetched Atom feed.")
                return response.read().decode('utf-8')
            else:
                raise NetworkError(f"Failed to fetch Atom feed. Status code: {response.status}")
    except HTTPError as e:
        logger.error(f"HTTPError fetching feed: {e.code} {e.reason}", exc_info=True)
        raise NetworkError(f"HTTP Error {e.code}: {e.reason}")
    except URLError as e:
        logger.error(f"URLError fetching feed: {e.reason}", exc_info=True)
        raise NetworkError(f"URL Error: {e.reason}")
    except Exception as e:
        logger.error(f"Unexpected error fetching feed: {e}", exc_info=True)
        raise

def parse_products_from_feed(feed_content):
    """Parses product information from the Atom feed XML content."""
    if not feed_content:
        return []

    logger.info("Parsing Atom feed content.")
    products = []
    try:
        root = ET.fromstring(feed_content)
        
        # Define namespaces used in the feed
        namespaces = {
            'atom': 'http://www.w3.org/2005/Atom',
            's': 'http://jadedpixel.com/-/spec/shopify'
        }

        for entry in root.findall('atom:entry', namespaces):
            product_data = {}
            
            title_element = entry.find('atom:title', namespaces)
            original_title = title_element.text.strip() if title_element is not None and title_element.text else "N/A"
            product_data['title'] = original_title

            # Parse cultivar and plant variety from title
            parsed_title_info = parse_with_botanical_field_names(original_title)
            product_data['common_name'] = parsed_title_info['common_name']
            product_data['cultivar_name'] = parsed_title_info['cultivar_name']

            link_element = entry.find('atom:link[@rel="alternate"][@type="text/html"]', namespaces)
            product_data['url'] = link_element.get('href') if link_element is not None else "N/A"
            
            vendor_element = entry.find('s:vendor', namespaces)
            product_data['vendor'] = vendor_element.text.strip() if vendor_element is not None and vendor_element.text else "N/A"

            product_type_element = entry.find('s:type', namespaces)
            product_data['product_type'] = product_type_element.text.strip() if product_type_element is not None and product_type_element.text else ""

            # Parse HTML summary for image and description
            summary_html_element = entry.find('atom:summary', namespaces)
            image_url = None
            description = ""
            if summary_html_element is not None and summary_html_element.text:
                summary_html_content = summary_html_element.text
                parser = SummaryHTMLParser()
                try:
                    parser.feed(summary_html_content)
                    parsed_summary_data = parser.get_data()
                    image_url = parsed_summary_data['image_url']
                    description = parsed_summary_data['description']
                except Exception as html_parse_err:
                    logger.warning(f"Could not parse HTML summary for {product_data.get('title', 'Unknown product')}: {html_parse_err}", exc_info=True)
                finally:
                    parser.close() # Ensure parser resources are freed
            
            product_data['image_url'] = image_url
            product_data['description'] = description.strip()

            # Extract tags
            product_data['tags'] = [tag.text for tag in entry.findall('s:tag', namespaces) if tag.text]

            # Extract variants
            variants_data = []
            for variant_element in entry.findall('s:variant', namespaces):
                var_title_element = variant_element.find('atom:title', namespaces) # Shopify uses atom:title for variant title
                var_title = var_title_element.text.strip() if var_title_element is not None and var_title_element.text else "N/A"
                
                # Parse weight from title
                weight_kg, original_value, original_unit = parse_weight_from_string(var_title)
                
                # Also check s:grams field as a fallback/validation
                grams_element = variant_element.find('s:grams', namespaces)
                if grams_element is not None and grams_element.text:
                    try:
                        grams_value = float(grams_element.text)
                        if grams_value > 0:
                            # If we didn't get weight from title, use grams
                            if weight_kg is None:
                                weight_kg = grams_value / 1000.0  # Convert grams to kg
                                original_value = grams_value
                                original_unit = 'g'
                            # If we got weight from title, validate against grams
                            else:
                                expected_grams = weight_kg * 1000
                                if abs(expected_grams - grams_value) > 1:  # Allow 1g tolerance
                                    logger.warning(f"Weight mismatch for {var_title}: parsed {weight_kg}kg vs {grams_value}g in feed")
                    except (ValueError, TypeError):
                        pass
                
                standardized_size = standardize_size_format(var_title)
                
                price_element = variant_element.find('s:price', namespaces)
                var_price = extract_price(price_element.text) if price_element is not None else None
                
                sku_element = variant_element.find('s:sku', namespaces)
                var_sku = sku_element.text.strip() if sku_element is not None and sku_element.text else "N/A"
                
                variants_data.append({
                    'size': standardized_size,
                    'price': var_price,
                    'sku': var_sku,
                    'is_variation_in_stock': False, # Default value, updated later with live data
                    'weight_kg': weight_kg,
                    'original_weight_value': original_value,
                    'original_weight_unit': original_unit,
                })
            product_data['variations'] = variants_data
            
            # Overall stock status is not available from the feed
            product_data['is_in_stock'] = False # Default value, updated later with live data

            products.append(product_data)
            logger.debug(f"Parsed product: {product_data['title']}")

    except ET.ParseError as e:
        logger.error(f"XML ParseError: Failed to parse Atom feed content. Error: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error parsing feed content: {e}", exc_info=True)
    
    logger.info(f"Successfully parsed {len(products)} products from the feed.")
    return products


@retry_on_failure(max_attempts=2, delay=3.0)
def scrape_product_page_details(page, product_url):
    """
    Scrapes product page for real-time stock information using Playwright.
    Prioritizes finding and parsing embedded JSON data for product variants.

    Args:
        page: Playwright page object.
        product_url: URL of the product page to scrape.

    Returns:
        A dictionary with stock information for variants, keyed by SKU:
        {
            "SKU123": {"is_in_stock": True, "title": "Variant Title 1"},
            "SKU456": {"is_in_stock": False, "title": "Variant Title 2"}
        }
        Returns an empty dictionary if stock info cannot be determined or page fails to load.
    """
    logger.info(f"Scraping product page for stock details: {product_url}")
    variant_stock_info = {}
    try:
        page.goto(product_url, timeout=60000, wait_until="domcontentloaded")
        # Common Shopify pattern for embedding product data
        json_data_script_locator = page.locator('script[type="application/json"][data-product-json]')
        # Alternative common pattern (often used by Shopify themes, might be in various IDs)
        json_data_script_alternative_locators = [
            page.locator('script[type="application/json"][id^="ProductJson-"]'), # Starts with ProductJson-
            page.locator('script[type="application/ld+json"]:contains("Product")') # More general, might need careful parsing
        ]

        product_json_text = None
        if json_data_script_locator.count() > 0:
            product_json_text = json_data_script_locator.first.text_content()
            logger.debug(f"Found product JSON using [data-product-json] for {product_url}")
        else:
            for i, alt_locator in enumerate(json_data_script_alternative_locators):
                if alt_locator.count() > 0:
                    # For ld+json, we need to be careful as it might be an array or a single object
                    # and might contain other schema types. We need the one that's a Product.
                    if "ld+json" in alt_locator.first.get_attribute("type"):
                        try:
                            ld_json_data_list = json.loads(alt_locator.first.text_content())
                            if isinstance(ld_json_data_list, list):
                                for item in ld_json_data_list:
                                    if isinstance(item, dict) and item.get("@type") == "Product":
                                        product_json_text = json.dumps(item) # Re-serialize the product part
                                        logger.debug(f"Found product JSON in ld+json array (locator {i+1}) for {product_url}")
                                        break
                            elif isinstance(ld_json_data_list, dict) and ld_json_data_list.get("@type") == "Product":
                                product_json_text = json.dumps(ld_json_data_list)
                                logger.debug(f"Found product JSON in single ld+json object (locator {i+1}) for {product_url}")
                        except json.JSONDecodeError as jde:
                            logger.warning(f"Could not parse ld+json content (locator {i+1}) for {product_url}: {jde}")
                        if product_json_text: break 
                    else:
                        product_json_text = alt_locator.first.text_content()
                        logger.debug(f"Found product JSON using alternative locator {i+1} for {product_url}")
                        break 
            if not product_json_text:
                 logger.warning(f"No embedded product JSON found on {product_url}. Stock status will be unreliable.")

        if product_json_text:
            try:
                product_data = json.loads(product_json_text)
                # The structure of this JSON can vary between themes.
                # Common paths: product_data['variants'] or product_data["offers"] (for ld+json)
                variants = product_data.get('variants', [])
                if not variants and product_data.get("@type") == "Product": # ld+json often uses 'offers'
                    offers = product_data.get('offers', [])
                    if isinstance(offers, dict): # Sometimes it's a single offer object
                        offers = [offers]
                    for offer in offers:
                        sku = offer.get('sku')
                        title = offer.get('name', product_data.get('name', 'Unknown Variant')) # Offer might have its own name or use product name
                        # Availability can be a URL like "http://schema.org/InStock" or a simple boolean
                        availability = offer.get('availability')
                        is_in_stock_offer = False
                        if isinstance(availability, str):
                            is_in_stock_offer = "instock" in availability.lower() or "limitedavailability" in availability.lower()
                        elif isinstance(availability, bool): # Less common in ld+json but possible
                            is_in_stock_offer = availability
                        
                        if sku:
                            variant_stock_info[sku] = {"is_in_stock": is_in_stock_offer, "title": title}
                        else:
                            logger.warning(f"Offer found without SKU in ld+json for {product_url}, title: {title}")
                else: # Standard Shopify product JSON variants
                    for variant in variants:
                        sku = variant.get('sku')
                        available = variant.get('available', False) # Default to False if not present
                        title = variant.get('title', variant.get('name', 'Unknown Variant'))
                        if sku:
                            variant_stock_info[sku] = {"is_in_stock": available, "title": title}
                        else:
                            logger.warning(f"Variant found without SKU for {product_url}, title: {title}")
                
                if variant_stock_info:
                    logger.info(f"Successfully extracted stock for {len(variant_stock_info)} variants from JSON on {product_url}")
                else:
                    logger.warning(f"Product JSON parsed, but no variants with SKUs found for {product_url}. Check JSON structure.")

            except json.JSONDecodeError as e:
                logger.error(f"Could not parse product JSON data from {product_url}: {e}", exc_info=True)
            except Exception as e_parse:
                logger.error(f"Error processing parsed product JSON for {product_url}: {e_parse}", exc_info=True)

        # Fallback (if no JSON or JSON parsing failed/yielded no usable SKUs)
        if not variant_stock_info:
            logger.info(f"No variant stock info from JSON for {product_url}. Attempting fallback: checking for general sold-out / add to cart button.")
            # This fallback is very basic and may not work well for multi-variant products.
            # It assumes if an "Add to cart" is present and not disabled, the product (or at least one variant) is in stock.
            # And if a prominent "Sold Out" is visible, it's out of stock.
            # This is a very broad check and often unreliable for true variant stock.

            sold_out_button_locator = page.locator('button:text-matches("(?i)Sold Out|Out of Stock")', timeout=5000).first
            add_to_cart_button_locator = page.locator(
                'button[type="submit"]:text-matches("(?i)Add to Cart|Add to Bag"):not([disabled]),'
                'input[type="submit"]:text-matches("(?i)Add to Cart|Add to Bag"):not([disabled])', timeout=5000
            ).first

            # Check for a product form with a select that might be disabled if all options are OOS
            # e.g., <select name="id" id="product-select-..." class="product-form__variants no-js">
            variant_select_disabled = page.locator('form[action*="/cart/add"] select[name="id"][disabled]', timeout=3000).count() > 0

            if sold_out_button_locator.count() > 0 and sold_out_button_locator.is_visible():
                logger.info(f"Fallback: 'Sold Out' indication found on {product_url}. Assuming all variants OOS.")
                # Cannot determine individual SKUs here, so this is a product-level OOS guess.
                # This is problematic if we need to update specific variants from the feed.
            elif variant_select_disabled:
                logger.info(f"Fallback: Variant select dropdown is disabled on {product_url}. Assuming all variants OOS.")
            elif add_to_cart_button_locator.count() > 0 and add_to_cart_button_locator.is_visible():
                logger.info(f"Fallback: 'Add to Cart' button found on {product_url}. Assuming at least one variant is IN STOCK.")
                # Again, cannot link to specific SKUs here.
            else:
                logger.warning(f"Fallback: Stock status unclear on {product_url} (no clear sold out/add to cart, or disabled select).")

    except PlaywrightTimeoutError as pte:
        logger.error(f"Playwright timeout loading product page {product_url}: {pte}", exc_info=True)
    except Exception as e:
        logger.error(f"Error scraping product page {product_url}: {e}", exc_info=True)
    
    if not variant_stock_info:
        logger.warning(f"Could not determine stock for any variants on {product_url} from page details.")
    return variant_stock_info


def main():
    """Main function to orchestrate the scraping process."""
    logger.info("Starting Damseeds scraper main process.")
    overall_start_time = time.time()

    try:
        feed_content = fetch_atom_feed(ATOM_FEED_URL)
    except Exception as e:
        logger.critical(f"Failed to fetch Atom feed: {e}")
        return

    # Products parsed from the Atom feed (basic info)
    atom_products = parse_products_from_feed(feed_content)

    if not atom_products:
        logger.info("No products found in the Atom feed. Exiting.")
        return

    detailed_products = []
    playwright_headless_mode = HEADLESS
    logger.info(f"Playwright headless mode: {playwright_headless_mode}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=playwright_headless_mode)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
            java_script_enabled=True,
            accept_downloads=False,
        )
        page = context.new_page()

        products_to_process_details_for = atom_products
        if TEST_MODE:
            logger.info(f"TEST_MODE is True. Limiting product detail scraping to 2 products.")
            products_to_process_details_for = atom_products[:2]

        for i, atom_product_data in enumerate(products_to_process_details_for):
            logger.info(f"\nProcessing product {i+1}/{len(products_to_process_details_for)} for details: {atom_product_data['title']} ({atom_product_data['url']})" )
            time.sleep(1) # Politeness delay

            # Scrape the live product page for stock details
            try:
                live_variant_stock_info = scrape_product_page_details(page, atom_product_data['url'])
            except Exception as e:
                logger.error(f"Failed to scrape product page details: {e}")
                live_variant_stock_info = {}

            # Update variants from Atom feed with live stock info
            updated_variants = []
            any_variant_in_stock = False
            for feed_variant in atom_product_data.get('variations', []):
                sku = feed_variant.get('sku')
                live_info = live_variant_stock_info.get(sku) if sku else None
                
                current_variant_data = feed_variant.copy() # Start with feed data
                if live_info:
                    current_variant_data['is_variation_in_stock'] = live_info['is_in_stock']
                    if live_info['is_in_stock']:
                        any_variant_in_stock = True
                    # Title consistency check (optional)
                    if live_info.get('title') and live_info['title'].lower() != feed_variant.get('size','').lower():
                        logger.debug(f"  Variant with SKU {sku} has title mismatch: Page='{live_info.get('title')}', using standardized format for consistency.")
                else:
                    current_variant_data['is_variation_in_stock'] = False # Assume OOS if not found on page / no SKU match
                    logger.warning(f"  SKU '{sku}' not found or no stock info on page {atom_product_data['url']}.")
                
                # Remove any old stock status fields if they exist
                current_variant_data.pop('stock_status_from_feed', None) 
                updated_variants.append(current_variant_data)
            
            # Create the final product entry
            final_product_entry = atom_product_data.copy()
            final_product_entry['variations'] = updated_variants
            final_product_entry['is_in_stock'] = any_variant_in_stock
            final_product_entry.pop('stock_status_from_feed', None) # Remove old product-level status

            # Validate product data
            if validate_product_data(final_product_entry, logger):
                detailed_products.append(final_product_entry)
            else:
                logger.warning(f"Product failed validation: {final_product_entry.get('title')}")

        logger.info("Closing browser.")
        browser.close()

    core_scrape_duration_seconds = time.time() - overall_start_time

    if detailed_products:
        save_products_to_json(
            products=detailed_products,
            output_dir=SHARED_OUTPUT_DIR,
            filename_prefix=f"{SUPPLIER_NAME}_microgreens_live_stock",
            source_site="https://www.damseeds.com",
            currency_code="CAD",
            scrape_duration=core_scrape_duration_seconds,
            logger=logger
        )
    else:
        logger.info("No products were scraped from Damseeds feed or processed for live details.")

    overall_duration_seconds = round(time.time() - overall_start_time, 2)
    logger.info(f"Damseeds scraper main process finished. Total duration: {overall_duration_seconds} seconds.")

if __name__ == "__main__":
    main()