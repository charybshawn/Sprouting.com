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
import logging
import logging.handlers

# --- Constants ---
ATOM_FEED_URL = "https://www.damseeds.com/collections/microgreens.atom"
SHARED_OUTPUT_DIR = "./scraper_data/json_files/"  # Shared with sprouting_scraper
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs") # Shared log dir
LOG_FILE = os.path.join(LOG_DIR, "damseeds_scraper.log")
SUPPLIER_NAME = "damseeds_com"

# --- Setup Logger ---
logger = logging.getLogger("DamseedsScraper")
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
            LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
        )
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Error setting up file logger for damseeds_scraper: {e}")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)

    logger.info("Damseeds Scraper logging configured. Saving logs to: %s", LOG_FILE)


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


def fetch_atom_feed(url):
    """Fetches the Atom feed content from the given URL."""
    logger.info(f"Fetching Atom feed from: {url}")
    try:
        with urllib.request.urlopen(url) as response:
            if response.status == 200:
                logger.info("Successfully fetched Atom feed.")
                return response.read().decode('utf-8')
            else:
                logger.error(f"Failed to fetch Atom feed. Status code: {response.status}")
                return None
    except HTTPError as e:
        logger.error(f"HTTPError fetching feed: {e.code} {e.reason}", exc_info=True)
        return None
    except URLError as e:
        logger.error(f"URLError fetching feed: {e.reason}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching feed: {e}", exc_info=True)
        return None

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
            product_data['title'] = title_element.text.strip() if title_element is not None and title_element.text else "N/A"

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
                
                parsed_weight_info = parse_weight_from_string(var_title)

                price_element = variant_element.find('s:price', namespaces)
                var_price = float(price_element.text) if price_element is not None and price_element.text else 0.0
                
                sku_element = variant_element.find('s:sku', namespaces)
                var_sku = sku_element.text.strip() if sku_element is not None and sku_element.text else "N/A"
                
                variants_data.append({
                    'title': var_title,
                    'price': var_price,
                    'sku': var_sku,
                    'stock_status_from_feed': 'Not Available', # Updated stock status
                    'weight_kg': parsed_weight_info['weight_kg'] if parsed_weight_info else None,
                    'original_weight_value': parsed_weight_info['value'] if parsed_weight_info else None,
                    'original_weight_unit': parsed_weight_info['unit'] if parsed_weight_info else None,
                })
            product_data['variants'] = variants_data
            
            # Overall stock status is not available from the feed
            product_data['stock_status_from_feed'] = 'Not Available' # Updated product-level stock status


            products.append(product_data)
            logger.debug(f"Parsed product: {product_data['title']}")

    except ET.ParseError as e:
        logger.error(f"XML ParseError: Failed to parse Atom feed content. Error: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error parsing feed content: {e}", exc_info=True)
    
    logger.info(f"Successfully parsed {len(products)} products from the feed.")
    return products


def parse_weight_from_string(text_string):
    """
    Parses weight information (value and unit) from a string and converts to kilograms.
    Handles grams, g, kilograms, kilo, kg, pounds, pound, lbs, lb.
    Returns a dictionary with 'value', 'unit', and 'weight_kg' or None if no match.
    """
    if not text_string:
        return None

    # Define conversion factors to kilograms
    TO_KG = {
        'grams': 0.001, 'gram': 0.001, 'g': 0.001,
        'kilos': 1.0, 'kilo': 1.0, 'kilograms': 1.0, 'kilogram': 1.0, 'kg': 1.0,
        'pounds': 0.45359237, 'pound': 0.45359237, 'lbs': 0.45359237, 'lb': 0.45359237,
        # Add other units like ounces if needed in the future
        # 'oz': 0.0283495, 'ounce': 0.0283495,
    }

    # Regex to capture value and unit
    # It looks for a number (int or float) followed by optional space and then one of the units.
    # Using word boundaries (\\b) for units to avoid partial matches (e.g., 'g' in 'grams').
    # Adjusted to handle cases like "22.5 kilos" vs "22.5kilos"
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
                'weight_kg': round(weight_kg, 6) #Rounding to avoid float precision issues
            }
        except ValueError:
            logger.warning(f"Could not convert value '{value_str}' to float for weight parsing in '{text_string}'")
            return None
    return None

def save_products_to_json(data_to_save, supplier_name_val, base_filename_prefix="products"):
    """Saves data to a JSON file in the SHARED_OUTPUT_DIR."""
    if not data_to_save.get("data"):
        logger.warning("No product data provided to save_products_to_json.")
        return

    try:
        os.makedirs(SHARED_OUTPUT_DIR, exist_ok=True)
    except OSError as e:
        logger.error(f"Error creating directory {SHARED_OUTPUT_DIR}: {e}. Please check permissions.", exc_info=True)
        return

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{supplier_name_val}_{base_filename_prefix}_{timestamp_str}.json"
    output_filename = os.path.join(SHARED_OUTPUT_DIR, filename)

    try:
        with open(output_filename, 'w', encoding='utf-8') as output_file:
            json.dump(data_to_save, output_file, ensure_ascii=False, indent=4)
        # Attempt to set permissions, handle potential errors gracefully
        try:
            os.chmod(output_filename, 0o664) # rw-rw-r--
        except OSError as e_chmod:
            logger.warning(f"Could not set permissions for {output_filename}: {e_chmod}")
        logger.info(f"Data saved to {output_filename}")
    except IOError as e:
        logger.error(f"Error writing to file {output_filename}: {e}", exc_info=True)


def main():
    """Main function to orchestrate the scraping process."""
    setup_logging()
    logger.info("Starting Damseeds scraper main process.")
    overall_start_time = time.time()

    feed_content = fetch_atom_feed(ATOM_FEED_URL)
    
    if not feed_content:
        logger.critical("Failed to fetch Atom feed. Exiting.")
        return

    scraped_products = parse_products_from_feed(feed_content)

    core_scrape_duration_seconds = round(time.time() - overall_start_time, 2) # Recalculate after parsing

    if scraped_products:
        current_timestamp_iso = datetime.now().isoformat()
        output_data = {
            "timestamp": current_timestamp_iso,
            "scrape_duration_seconds": core_scrape_duration_seconds,
            "source_site": "https://www.damseeds.com",
            "product_count": len(scraped_products),
            "data": scraped_products
        }
        save_products_to_json(output_data, supplier_name_val=SUPPLIER_NAME, base_filename_prefix="microgreens_atom")
    else:
        logger.info("No products were scraped from Damseeds feed.")

    overall_duration_seconds = round(time.time() - overall_start_time, 2)
    logger.info(f"Damseeds scraper main process finished. Total duration: {overall_duration_seconds} seconds.")

if __name__ == "__main__":
    main() 