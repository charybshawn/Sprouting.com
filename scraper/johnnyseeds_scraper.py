#!/usr/bin/env python3
"""
Johnny's Seeds microgreen scraper.
Scrapes microgreen seeds from johnnyseeds.com using the PageNavigationScraper base class.
"""

import os
import json
import time
import re
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from base_scraper import PageNavigationScraper
from seed_name_parser import parse_with_botanical_field_names
from scraper_utils import (
    parse_weight_from_string, standardize_size_format, extract_price,
    clean_text, is_organic_product, make_absolute_url,
    calculate_canadian_import_costs, ScraperError, NetworkError, ParseError
)

# --- Constants ---
BASE_URL = "https://johnnyseeds.com"
MICROGREENS_CATEGORY_URL = "https://johnnyseeds.com/vegetables/microgreens/"
OUTPUT_DIR = "./scraper_data/json_files/johnny_seeds"
SUPPLIER_NAME = "johnnyseeds_com"
CURRENCY_CODE = "USD"  # Johnny's Seeds uses USD pricing

class JohnnySeedsScaper(PageNavigationScraper):
    """Scraper for Johnny's Seeds microgreen products."""
    
    def __init__(self, test_mode: bool = False, test_limit: int = 3):
        """
        Initialize Johnny's Seeds scraper.
        
        Args:
            test_mode: Whether to run in test mode (limited scraping)
            test_limit: Number of products to scrape in test mode
        """
        super().__init__(
            supplier_name=SUPPLIER_NAME,
            source_site=BASE_URL,
            output_dir=OUTPUT_DIR,
            currency_code=CURRENCY_CODE,
            headless=True,
            test_mode=test_mode,
            test_limit=test_limit
        )
        # Enable debug logging for variation parsing
        self.logger.setLevel(logging.DEBUG)
    
    def get_start_urls(self) -> List[str]:
        """Get the list of starting URLs to scrape."""
        return [MICROGREENS_CATEGORY_URL]
    
    def extract_product_links(self, page_url: str) -> List[Dict[str, Any]]:
        """
        Extract product links from a Johnny's Seeds microgreen category page.
        
        Args:
            page_url: URL of the category page
            
        Returns:
            List of product dictionaries with basic info
        """
        self.logger.info(f"Extracting product links from: {page_url}")
        products = []
        
        try:
            # Navigate to the page if not already there
            if self.page.url != page_url:
                self.page.goto(page_url, timeout=30000, wait_until="domcontentloaded")
                time.sleep(2)  # Allow time for dynamic content
                
                # Handle popups if present
                self._handle_popups()
            
            # Wait for product grid to load initially
            try:
                self.page.wait_for_selector('.product-tile', timeout=10000)
            except PlaywrightTimeoutError:
                self.logger.warning("Initial product tiles not found, trying to proceed anyway")
            
            # Handle infinite scroll or "Load More" functionality
            self._load_all_products()
            
            # Find all product tiles after loading
            product_tiles = self.page.locator('.product-tile').all()
            self.logger.info(f"Found {len(product_tiles)} product tiles")
            
            for tile in product_tiles:
                try:
                    # Extract product URL
                    link_element = tile.locator('a.tile-name-link').first
                    if link_element.count() == 0:
                        continue
                        
                    relative_url = link_element.get_attribute('href')
                    if not relative_url:
                        continue
                    
                    product_url = make_absolute_url(relative_url, BASE_URL)
                    
                    # Extract product title
                    title_element = tile.locator('.tile-name.product-name').first
                    if title_element.count() == 0:
                        continue
                        
                    title = clean_text(title_element.text_content())
                    if not title:
                        continue
                    
                    # Parse botanical information from title
                    parsed_info = parse_with_botanical_field_names(title)
                    
                    # Skip if we can't identify the plant type
                    if parsed_info['common_name'] == "N/A":
                        self.logger.debug(f"Skipping '{title}' - no matching common name")
                        continue
                    
                    # Check if it's organic
                    organic = is_organic_product(title)
                    
                    product_data = {
                        'title': title,
                        'url': product_url,
                        'common_name': parsed_info['common_name'],
                        'cultivar_name': parsed_info['cultivar_name'],
                        'organic': organic
                    }
                    
                    products.append(product_data)
                    self.logger.debug(f"Found product: {title}")
                    
                except Exception as e:
                    self.logger.warning(f"Error processing product tile: {e}")
                    continue
            
        except PlaywrightTimeoutError:
            self.logger.error(f"Timeout waiting for products to load on {page_url}")
        except Exception as e:
            self.logger.error(f"Error extracting product links from {page_url}: {e}")
        
        self.logger.info(f"Extracted {len(products)} products from {page_url}")
        return products
    
    def get_next_page_url(self, current_url: str) -> Optional[str]:
        """
        Get the URL of the next page, if pagination exists.
        
        Args:
            current_url: Current page URL
            
        Returns:
            Next page URL or None if no more pages
        """
        try:
            # Look for pagination next button
            next_button = self.page.locator('.pagination__next:not(.pagination__next--disabled)').first
            if next_button.count() > 0:
                next_href = next_button.get_attribute('href')
                if next_href:
                    return make_absolute_url(next_href, BASE_URL)
        except Exception as e:
            self.logger.debug(f"Error checking for next page: {e}")
        
        return None
    
    def _handle_popups(self) -> None:
        """Handle various popups that might block interaction."""
        try:
            # Cookie consent selectors
            consent_selectors = [
                '#onetrust-accept-btn-handler',  # OneTrust Accept All
                'button:has-text("Accept All")',
                'button:has-text("Accept")',
                '.onetrust-accept-btn',
                '[data-testid="accept-all"]'
            ]
            
            # Email signup modal selectors
            modal_close_selectors = [
                '#ltkpopup-container .ltkmodal-close',  # Email signup close
                '.ltkmodal-close',
                '.modal-close',
                'button:has-text("Close")',
                '[aria-label="Close"]',
                '.close-modal',
                '[data-dismiss="modal"]'
            ]
            
            # Try cookie consent first
            for selector in consent_selectors:
                accept_button = self.page.locator(selector).first
                if accept_button.count() > 0 and accept_button.is_visible():
                    self.logger.info(f"Found cookie consent button: {selector}")
                    accept_button.click()
                    time.sleep(2)
                    self.logger.info("Accepted cookie consent")
                    break
            
            # Try closing email signup modals
            for selector in modal_close_selectors:
                close_button = self.page.locator(selector).first
                if close_button.count() > 0 and close_button.is_visible():
                    self.logger.info(f"Found modal close button: {selector}")
                    close_button.click()
                    time.sleep(1)
                    self.logger.info("Closed modal")
                    break
                    
        except Exception as e:
            self.logger.debug(f"Error handling popups: {e}")
    
    def _load_all_products(self) -> None:
        """
        Handle load more functionality for Johnny's Seeds pagination.
        Uses the specific link structure: a.btn.more with href containing start= and sz= parameters.
        """
        max_attempts = 10  # Should be enough for 112 products (12 + 36 + 36 + 28 = 112)
        attempt_count = 0
        
        while attempt_count < max_attempts:
            current_product_count = self.page.locator('.product-tile').count()
            self.logger.info(f"Attempt {attempt_count + 1}: Currently have {current_product_count} products")
            
            # Look for the specific "View More" link with Johnny's Seeds structure
            view_more_link = self.page.locator('a.btn.more').first
            
            if view_more_link.count() > 0 and view_more_link.is_visible():
                try:
                    # Get the link text and href for debugging
                    link_text = view_more_link.text_content().strip()
                    href = view_more_link.get_attribute('href')
                    self.logger.info(f"Found 'View More' link: '{link_text}' -> {href}")
                    
                    # Handle any popups before clicking
                    self._handle_popups()
                    
                    # Click the link
                    view_more_link.click()
                    self.logger.info("Clicked 'View More' link")
                    
                    # Wait for the page to load new content
                    time.sleep(3)
                    
                    # Check if more products were loaded
                    new_product_count = self.page.locator('.product-tile').count()
                    if new_product_count > current_product_count:
                        self.logger.info(f"SUCCESS! Products loaded: {current_product_count} -> {new_product_count}")
                        attempt_count += 1
                        continue
                    else:
                        self.logger.info("Link click didn't increase product count")
                        break
                        
                except Exception as e:
                    self.logger.warning(f"Error clicking 'View More' link: {e}")
                    break
            else:
                # No more "View More" link found
                self.logger.info("No 'View More' link found, all products loaded")
                break
                
            attempt_count += 1
        
        final_count = self.page.locator('.product-tile').count()
        self.logger.info(f"Finished loading. Final product count: {final_count}")
    
    def _calculate_canadian_costs(self, usd_price: float) -> Dict[str, float]:
        """
        Calculate detailed Canadian import costs using the standardized function.
        
        Args:
            usd_price: Price in USD
            
        Returns:
            Dictionary with detailed cost breakdown
        """
        return calculate_canadian_import_costs(
            base_price=usd_price,
            source_currency="USD",
            province="BC",  # Default to BC, could be made configurable
            min_shipping=12.50,  # Johnny's Seeds shipping range
            max_shipping=125.00,
            brokerage_fee=17.50,
            commercial_use=True  # Seeds are tax exempt for commercial use
        )
    
    def scrape_product_details(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scrape detailed information for a single Johnny's Seeds product.
        
        Args:
            product: Product dictionary from extract_product_links
            
        Returns:
            Complete product dictionary with all required fields
        """
        self.logger.info(f"Scraping details for: {product['title']}")
        
        # Start with basic product info
        detailed_product = product.copy()
        detailed_product['is_in_stock'] = False
        detailed_product['variations'] = []
        
        try:
            # Navigate to product page
            self.page.goto(product['url'], timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)  # Allow time for JavaScript to load
            
            # Look for JSON-LD structured data first (most reliable)
            json_ld_data = self._extract_json_ld_data()
            json_ld_variations = []
            if json_ld_data:
                self.logger.debug(f"Found JSON-LD data: {json.dumps(json_ld_data, indent=2)[:500]}...")
                json_ld_variations = self._parse_json_ld_variations(json_ld_data)
                self.logger.debug(f"Parsed {len(json_ld_variations)} variations from JSON-LD")
                # Debug: Log what we found in JSON-LD
                for i, var in enumerate(json_ld_variations):
                    self.logger.debug(f"JSON-LD variation {i+1}: {var['size']} - ${var['price']}")
                if len(json_ld_variations) > 1:  # Only return if multiple variations found
                    detailed_product['variations'] = json_ld_variations
                    detailed_product['is_in_stock'] = any(var['is_variation_in_stock'] for var in json_ld_variations)
                    return detailed_product
            
            # Fallback: Look for embedded product JSON
            product_json = self._extract_product_json()
            product_json_variations = []
            if product_json:
                self.logger.debug(f"Found product JSON: {json.dumps(product_json, indent=2)[:500]}...")
                product_json_variations = self._parse_product_json_variations(product_json)
                self.logger.debug(f"Parsed {len(product_json_variations)} variations from product JSON")
                if len(product_json_variations) > 1:  # Only return if multiple variations found
                    detailed_product['variations'] = product_json_variations
                    detailed_product['is_in_stock'] = any(var['is_variation_in_stock'] for var in product_json_variations)
                    return detailed_product
            
            # Final fallback: Parse HTML directly or use best available data
            self.logger.debug("Using HTML parsing fallback for variations")
            html_variations = self._parse_html_variations()
            self.logger.debug(f"Parsed {len(html_variations)} variations from HTML")
            # Debug: Log what we found in HTML
            for i, var in enumerate(html_variations):
                self.logger.debug(f"HTML variation {i+1}: {var['size']} - ${var['price']} (SKU: {var['sku']})")
            
            # Use the best available variations (prioritize HTML if it found multiple, otherwise use any available)
            if len(html_variations) > 1:
                variations = html_variations
            elif len(product_json_variations) >= 1:
                variations = product_json_variations
            elif len(json_ld_variations) >= 1:
                variations = json_ld_variations
            else:
                variations = html_variations
            
            detailed_product['variations'] = variations
            detailed_product['is_in_stock'] = any(var['is_variation_in_stock'] for var in variations)
            
        except Exception as e:
            self.logger.error(f"Error scraping product details for {product['url']}: {e}")
            # Add error variation to maintain data structure
            cost_breakdown = self._calculate_canadian_costs(0.0)
            detailed_product['variations'] = [{
                'size': 'Error - could not parse',
                'price': 0.0,
                'is_variation_in_stock': False,
                'weight_kg': None,
                'original_weight_value': None,
                'original_weight_unit': None,
                'sku': 'N/A',
                'canadian_costs': cost_breakdown
            }]
        
        return detailed_product
    
    def _extract_json_ld_data(self) -> Optional[Dict[str, Any]]:
        """Extract JSON-LD structured data from the page."""
        try:
            json_ld_scripts = self.page.locator('script[type="application/ld+json"]').all()
            for script in json_ld_scripts:
                content = script.text_content()
                if content:
                    data = json.loads(content)
                    # Look for Product schema
                    if isinstance(data, dict) and data.get('@type') == 'Product':
                        return data
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and item.get('@type') == 'Product':
                                return item
        except Exception as e:
            self.logger.debug(f"Error extracting JSON-LD data: {e}")
        return None
    
    def _extract_product_json(self) -> Optional[Dict[str, Any]]:
        """Extract embedded product JSON from script tags."""
        try:
            # Common patterns for Salesforce Commerce Cloud / Johnny's Seeds
            selectors = [
                'script[data-product-json]',
                'script[id*="product"]',
                'script:has-text("variants")',
                'script:has-text("product")'
            ]
            
            for selector in selectors:
                scripts = self.page.locator(selector).all()
                for script in scripts:
                    content = script.text_content()
                    if content and ('variants' in content or 'offers' in content):
                        try:
                            # Try to parse as JSON
                            data = json.loads(content)
                            if isinstance(data, dict) and ('variants' in data or 'offers' in data):
                                return data
                        except json.JSONDecodeError:
                            # Might be JavaScript, try to extract JSON part
                            json_match = re.search(r'\{.*\}', content, re.DOTALL)
                            if json_match:
                                try:
                                    data = json.loads(json_match.group())
                                    if isinstance(data, dict) and ('variants' in data or 'offers' in data):
                                        return data
                                except json.JSONDecodeError:
                                    continue
        except Exception as e:
            self.logger.debug(f"Error extracting product JSON: {e}")
        return None
    
    def _parse_json_ld_variations(self, json_ld_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse variations from JSON-LD structured data."""
        variations = []
        
        try:
            offers = json_ld_data.get('offers', [])
            if isinstance(offers, dict):
                offers = [offers]
            
            for offer in offers:
                # Extract price
                price = extract_price(str(offer.get('price', 0)))
                
                # Extract SKU
                sku = offer.get('sku', 'N/A')
                
                # Extract size/name information
                name = offer.get('name', '')
                if not name:
                    name = json_ld_data.get('name', '')
                
                # Parse weight from name
                weight_kg, original_value, original_unit = parse_weight_from_string(name)
                
                # Skip packet variations
                if 'packet' in name.lower():
                    continue
                
                # Standardize size format
                size = standardize_size_format(name)
                
                # Check availability
                availability = offer.get('availability', '').lower()
                is_in_stock = 'instock' in availability or 'limitedavailability' in availability
                
                # Calculate Canadian import costs
                cost_breakdown = self._calculate_canadian_costs(price or 0.0)
                
                variation = {
                    'size': size,
                    'price': price or 0.0,
                    'is_variation_in_stock': is_in_stock,
                    'weight_kg': weight_kg,
                    'original_weight_value': original_value,
                    'original_weight_unit': original_unit,
                    'sku': sku,
                    'canadian_costs': cost_breakdown
                }
                
                variations.append(variation)
                
        except Exception as e:
            self.logger.error(f"Error parsing JSON-LD variations: {e}")
        
        return variations
    
    def _parse_product_json_variations(self, product_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse variations from product JSON data."""
        variations = []
        
        try:
            variants = product_data.get('variants', [])
            
            for variant in variants:
                # Extract price
                price = extract_price(str(variant.get('price', 0)))
                
                # Extract SKU
                sku = variant.get('sku', 'N/A')
                
                # Extract size/title
                title = variant.get('title', variant.get('name', ''))
                
                # Parse weight from title
                weight_kg, original_value, original_unit = parse_weight_from_string(title)
                
                # Skip packet variations
                if 'packet' in title.lower():
                    continue
                
                # Standardize size format
                size = standardize_size_format(title)
                
                # Check availability
                is_in_stock = variant.get('available', False)
                
                # Calculate Canadian import costs
                cost_breakdown = self._calculate_canadian_costs(price or 0.0)
                
                variation = {
                    'size': size,
                    'price': price or 0.0,
                    'is_variation_in_stock': is_in_stock,
                    'weight_kg': weight_kg,
                    'original_weight_value': original_value,
                    'original_weight_unit': original_unit,
                    'sku': sku,
                    'canadian_costs': cost_breakdown
                }
                
                variations.append(variation)
                
        except Exception as e:
            self.logger.error(f"Error parsing product JSON variations: {e}")
        
        return variations
    
    def _parse_html_variations(self) -> List[Dict[str, Any]]:
        """Parse variations by looking for size dropdown selectors on Johnny's Seeds."""
        variations = []
        
        try:
            # First, try to find size/variation selectors on the page
            # Johnny's Seeds typically uses select dropdowns or option buttons for sizes
            size_selectors = [
                'select[data-attribute="size"]',
                'select[name*="size"]',
                'select[id*="size"]',
                '.product-options select',
                '[data-size-selector]',
                '.size-selector'
            ]
            
            size_dropdown = None
            for selector in size_selectors:
                elements = self.page.locator(selector)
                if elements.count() > 0:
                    size_dropdown = elements.first
                    self.logger.info(f"Found size dropdown using selector: {selector}")
                    break
            
            if size_dropdown:
                # Extract options from the dropdown
                options = size_dropdown.locator('option').all()
                self.logger.info(f"Found {len(options)} size options in dropdown")
                
                for option in options:
                    try:
                        option_value = option.get_attribute('value')
                        option_text = clean_text(option.text_content())
                        
                        # Skip empty or default options
                        if not option_value or option_value in ['', 'select', 'choose']:
                            continue
                        
                        self.logger.debug(f"Processing option: value='{option_value}', text='{option_text}'")
                        
                        # Select this option to get the price for this size
                        size_dropdown.select_option(option_value)
                        time.sleep(1)  # Wait for price to update
                        
                        # Extract the updated price
                        price_elem = self.page.locator('.price .value, .product-price, .sales-price').first
                        price = 0.0
                        if price_elem.count() > 0:
                            price_text = price_elem.text_content()
                            price = extract_price(price_text) or 0.0
                        
                        # Parse weight and size information
                        weight_kg, original_value, original_unit = parse_weight_from_string(option_text)
                        size = standardize_size_format(option_text)
                        
                        # Check stock status
                        sold_out_elem = self.page.locator('.sold-out, .out-of-stock, [data-soldout="true"]').first
                        is_in_stock = sold_out_elem.count() == 0
                        
                        # Calculate Canadian import costs
                        cost_breakdown = self._calculate_canadian_costs(price)
                        
                        variation = {
                            'size': size,
                            'price': price,
                            'is_variation_in_stock': is_in_stock,
                            'weight_kg': weight_kg,
                            'original_weight_value': original_value,
                            'original_weight_unit': original_unit,
                            'sku': option_value,  # Use the option value as SKU
                            'canadian_costs': cost_breakdown
                        }
                        
                        variations.append(variation)
                        self.logger.info(f"Added dropdown variant: {size} - ${price} (SKU: {option_value})")
                        
                    except Exception as e:
                        self.logger.warning(f"Error processing size option: {e}")
                        continue
                
                if variations:
                    return variations
            
            # Fallback: Use direct API approach since the previous test succeeded with this method
            # I need to manually construct the variation URLs for all known size options
            self.logger.info("No size dropdown found, constructing known size variation URLs")
            
            # Extract the base product ID from the URL
            url_path = self.page.url
            # Look for patterns like: 5515MG, 2566, 4119M, 2566G, 3303M, etc.
            
            # Try multiple extraction patterns in order of specificity
            base_sku = None
            
            # Pattern 1: -[SKU].html (most common)
            base_sku_match = re.search(r'-([0-9A-Z]+)\.html', url_path)
            if base_sku_match:
                base_sku = base_sku_match.group(1)
            
            # Pattern 2: seed-[SKU].html  
            if not base_sku:
                base_sku_match = re.search(r'seed-([0-9A-Z]+)\.html', url_path)
                if base_sku_match:
                    base_sku = base_sku_match.group(1)
            
            # Pattern 2b: [product]-seed-[SKU].html or [product]-microgreen-seed-[SKU].html
            if not base_sku:
                base_sku_match = re.search(r'(?:microgreen-)?seed-([0-9A-Z]+)\.html', url_path)
                if base_sku_match:
                    base_sku = base_sku_match.group(1)
            
            # Pattern 3: Any [SKU].html at end
            if not base_sku:
                base_sku_match = re.search(r'([0-9A-Z]+)\.html$', url_path)
                if base_sku_match:
                    base_sku = base_sku_match.group(1)
            
            # Pattern 4: Extract from any position in URL path
            if not base_sku:
                # Look for patterns like 2566, 3303M, 4119M in the URL
                all_matches = re.findall(r'([0-9]+[A-Z]*)', url_path)
                # Take the longest match (likely the product SKU)
                if all_matches:
                    base_sku = max(all_matches, key=len)
            
            if not base_sku:
                self.logger.warning(f"Could not extract base SKU from URL: {url_path}")
                return []
            self.logger.info(f"Extracted base SKU: {base_sku}")
            
            # Johnny's Seeds appears to use consistent SKU patterns for size variations
            # Based on previous successful results: .26 (1/4 oz), .30 (4 oz), .32 (1 oz), .36 (5 oz), .38 (25 oz)
            size_variations = [
                ('26', '0.25 oz'),  # 1/4 oz converted to decimal
                ('30', '4 oz'), 
                ('32', '1 oz'),
                ('36', '5 oz'),
                ('38', '25 oz')
            ]
            
            for suffix, size_name in size_variations:
                try:
                    sku = f"{base_sku}.{suffix}"
                    variation_url = f"https://johnnyseeds.com/on/demandware.store/Sites-JSS-Site/en_US/Product-Variation?pid={sku}&quantity=1"
                    
                    self.logger.info(f"Fetching variation data for {size_name}: {variation_url}")
                    
                    # Navigate to the variation URL
                    response = self.page.goto(variation_url, timeout=10000, wait_until="domcontentloaded")
                    
                    if response and response.status == 200:
                        # Wait for content to load
                        time.sleep(1)
                        
                        # Look for JSON response data
                        if 'application/json' in response.headers.get('content-type', ''):
                            try:
                                import json
                                json_text = self.page.locator('body').text_content()
                                json_data = json.loads(json_text)
                                
                                # Extract from product data
                                product_data = json_data.get('product', {})
                                if product_data:
                                    # Extract price from product data
                                    price_info = product_data.get('price', {})
                                    price = 0.0
                                    if isinstance(price_info, dict):
                                        if 'sales' in price_info:
                                            sales_price = price_info['sales']
                                            if isinstance(sales_price, dict):
                                                price = float(sales_price.get('value', 0))
                                            else:
                                                price = float(sales_price) if sales_price else 0
                                        elif 'list' in price_info:
                                            list_price = price_info['list']
                                            if isinstance(list_price, dict):
                                                price = float(list_price.get('value', 0))
                                            else:
                                                price = float(list_price) if list_price else 0
                                    
                                    # Extract product details
                                    product_sku = product_data.get('id', sku)
                                    available = product_data.get('available', True)
                                    product_name = product_data.get('productName', product_data.get('name', ''))
                                    
                                    # Clean up: Remove debug logging for production use
                                    
                                    # Extract actual size information from variationAttributes
                                    actual_size = None
                                    variation_attrs = product_data.get('variationAttributes', [])
                                    
                                    # Look for the size attribute that matches current SKU
                                    for attr in variation_attrs:
                                        if attr.get('attributeId') == 'sizecode':
                                            for value in attr.get('values', []):
                                                if value.get('pid') == sku:
                                                    actual_size = value.get('displayValue')
                                                    self.logger.debug(f"Found actual size for {sku}: {actual_size}")
                                                    break
                                    
                                    if actual_size:
                                        # Parse size and weight information from the actual API size
                                        weight_kg, original_value, original_unit = parse_weight_from_string(actual_size)
                                        size = standardize_size_format(actual_size)
                                        self.logger.debug(f"Parsed size '{actual_size}': weight={weight_kg}kg, original={original_value} {original_unit}")
                                    else:
                                        # Fallback to hardcoded size_name only if API doesn't provide size info
                                        weight_kg, original_value, original_unit = parse_weight_from_string(size_name)
                                        size = standardize_size_format(size_name)
                                        self.logger.warning(f"Fallback to hardcoded '{size_name}': weight={weight_kg}kg, original={original_value} {original_unit}")
                                    
                                    if price > 0:
                                        cost_breakdown = self._calculate_canadian_costs(price)
                                        
                                        variation = {
                                            'size': size,
                                            'price': price,
                                            'is_variation_in_stock': bool(available),
                                            'weight_kg': weight_kg,
                                            'original_weight_value': original_value,
                                            'original_weight_unit': original_unit,
                                            'sku': product_sku,
                                            'canadian_costs': cost_breakdown
                                        }
                                        
                                        variations.append(variation)
                                        self.logger.info(f"Added size variant: {size} - ${price} (SKU: {product_sku})")
                                    else:
                                        self.logger.warning(f"No price found for size {size_name} (SKU: {sku})")
                                
                            except json.JSONDecodeError:
                                self.logger.debug(f"Response is not valid JSON for {sku}")
                        else:
                            self.logger.debug(f"Response is not JSON for {sku}")
                    else:
                        self.logger.warning(f"Failed to fetch variation for {sku}: {response.status if response else 'No response'}")
                        
                except Exception as e:
                    self.logger.warning(f"Error fetching variation for {size_name} (SKU: {sku}): {e}")
                    continue
            
            if variations:
                return variations
            
            # Final fallback: Use the older Product-Variation URL approach
            self.logger.info("Direct variation approach failed, trying Product-Variation URL discovery")
            form_elements = self.page.locator('[data-url*="Product-Variation"]').all()
            self.logger.info(f"Found {len(form_elements)} elements with Product-Variation URLs")
            
            # Extract unique product IDs from the data-url attributes
            product_urls = set()
            for element in form_elements:
                data_url = element.get_attribute('data-url')
                if data_url and 'pid=' in data_url:
                    # Extract the full URL for fetching product data
                    if data_url.startswith('/'):
                        full_url = f"https://johnnyseeds.com{data_url}"
                    else:
                        full_url = data_url
                    product_urls.add(full_url)
            
            self.logger.info(f"Found {len(product_urls)} unique product variation URLs")
            
            # Fetch data for each variation URL
            url_list = list(product_urls)[:5]  # Convert set to list and limit to first 5 for debugging
            for url in url_list:
                try:
                    self.logger.info(f"Fetching variation data from: {url}")
                    
                    # Navigate to the variation URL to get pricing data
                    response = self.page.goto(url, timeout=10000, wait_until="domcontentloaded")
                    
                    if response and response.status == 200:
                        # Wait for content to load
                        time.sleep(1)
                        
                        # Debug: Log the response content
                        page_content = self.page.content()
                        self.logger.debug(f"Response content length: {len(page_content)}")
                        
                        # Look for JSON response data
                        if 'application/json' in response.headers.get('content-type', ''):
                            # This is a JSON response, try to parse it directly
                            try:
                                import json
                                json_text = self.page.locator('body').text_content()
                                json_data = json.loads(json_text)
                                self.logger.info(f"JSON response keys: {json_data.keys()}")
                                
                                # Extract price from JSON response - look in 'product' key first
                                price = 0.0
                                sku = 'N/A'
                                product_name = ''
                                available = True
                                
                                # Johnny's Seeds puts the product data in the 'product' key
                                product_data = json_data.get('product', {})
                                if product_data:
                                    self.logger.debug(f"Product data keys: {product_data.keys()}")
                                    
                                    # Extract price from product data
                                    price_info = product_data.get('price', {})
                                    if isinstance(price_info, dict):
                                        # Try sales price first
                                        if 'sales' in price_info:
                                            sales_price = price_info['sales']
                                            if isinstance(sales_price, dict):
                                                price = float(sales_price.get('value', 0))
                                            else:
                                                price = float(sales_price) if sales_price else 0
                                        # Try list price as fallback
                                        elif 'list' in price_info:
                                            list_price = price_info['list']
                                            if isinstance(list_price, dict):
                                                price = float(list_price.get('value', 0))
                                            else:
                                                price = float(list_price) if list_price else 0
                                    
                                    # Extract product details
                                    sku = product_data.get('id', product_data.get('masterId', 'N/A'))
                                    product_name = product_data.get('productName', product_data.get('name', ''))
                                    available = product_data.get('available', True)
                                    
                                    self.logger.info(f"Extracted from product data: SKU={sku}, Price=${price}, Name={product_name}")
                                
                                # Fallback: Look for common price fields in the root JSON response
                                if price == 0.0:
                                    for price_field in ['price', 'amount', 'cost', 'value', 'unitPrice']:
                                        if price_field in json_data:
                                            price_data = json_data[price_field]
                                            if isinstance(price_data, dict):
                                                # Try to get sales price
                                                price = price_data.get('sales', {}).get('value', 0)
                                                if not price:
                                                    price = price_data.get('list', {}).get('value', 0)
                                                if not price:
                                                    price = price_data.get('value', 0)
                                            else:
                                                price = float(price_data) if price_data else 0
                                            
                                            if price > 0:
                                                break
                                    
                                    # Look for SKU in root
                                    if sku == 'N/A':
                                        for sku_field in ['id', 'sku', 'productId']:
                                            if sku_field in json_data:
                                                sku = json_data[sku_field]
                                                break
                                
                                if price > 0:
                                    # Use the product name we already extracted from product_data
                                    if not product_name:
                                        product_name = json_data.get('productName', json_data.get('name', ''))
                                    weight_kg, original_value, original_unit = parse_weight_from_string(product_name)
                                    size = standardize_size_format(product_name)
                                    
                                    cost_breakdown = self._calculate_canadian_costs(price)
                                    
                                    variation_data = {
                                        'size': size,
                                        'price': price,
                                        'is_variation_in_stock': available,
                                        'weight_kg': weight_kg,
                                        'original_weight_value': original_value,
                                        'original_weight_unit': original_unit,
                                        'sku': sku,
                                        'canadian_costs': cost_breakdown
                                    }
                                    
                                    variations.append(variation_data)
                                    self.logger.info(f"Added JSON variant: {size} - ${price} (SKU: {sku})")
                                    continue
                                
                            except json.JSONDecodeError:
                                self.logger.debug("Response is not valid JSON")
                        
                        # Fallback to HTML extraction
                        variation_data = self._extract_variation_from_page()
                        if variation_data:
                            variations.append(variation_data)
                            self.logger.info(f"Added HTML variant: {variation_data['size']} - ${variation_data['price']} (SKU: {variation_data['sku']})")
                        
                except Exception as e:
                    self.logger.warning(f"Error fetching variation from {url}: {e}")
                    continue
            
            if variations:
                return variations
            
            # If no size selector found, create a single default variation
            if not variations:
                self.logger.debug("No size selector found, creating default variation")
                
                # Get product title for size
                title_elem = self.page.locator('h1, .product-title, .product-name').first
                product_title = ""
                if title_elem.count() > 0:
                    product_title = clean_text(title_elem.text_content())
                
                # Get base price
                price_elem = self.page.locator('.price .value, .product-price').first
                base_price = 0.0
                if price_elem.count() > 0:
                    price_text = price_elem.text_content()
                    base_price = extract_price(price_text) or 0.0
                
                weight_kg, original_value, original_unit = parse_weight_from_string(product_title)
                
                # Check if sold out
                sold_out_elem = self.page.locator('.sold-out, .out-of-stock, [data-soldout="true"]').first
                is_in_stock = sold_out_elem.count() == 0
                
                # Calculate Canadian import costs
                cost_breakdown = self._calculate_canadian_costs(base_price)
                
                variations.append({
                    'size': standardize_size_format(product_title) or 'Standard',
                    'price': base_price,
                    'is_variation_in_stock': is_in_stock,
                    'weight_kg': weight_kg,
                    'original_weight_value': original_value,
                    'original_weight_unit': original_unit,
                    'sku': 'N/A',
                    'canadian_costs': cost_breakdown
                })
            
        except Exception as e:
            self.logger.error(f"Error parsing HTML variations: {e}")
        
        return variations
    
    def _extract_variation_from_page(self) -> Optional[Dict[str, Any]]:
        """Extract variation data from the current page."""
        try:
            # Wait for the page to fully load pricing data
            time.sleep(2)
            
            # Get the page content and extract JSON data if available
            page_content = self.page.content()
            
            # Look for multiple JSON patterns that might contain variant pricing
            import re
            import json
            
            # Try different JSON patterns
            json_patterns = [
                r'window\.product\s*=\s*({.*?});',
                r'productData\s*=\s*({.*?});',
                r'pdpData\s*=\s*({.*?});',
                r'"product"\s*:\s*({.*?})',
                r'var\s+product\s*=\s*({.*?});'
            ]
            
            for pattern in json_patterns:
                json_match = re.search(pattern, page_content, re.DOTALL)
                if json_match:
                    try:
                        product_data = json.loads(json_match.group(1))
                        
                        # Extract size/name from product data
                        product_name = product_data.get('productName', '')
                        sku = product_data.get('id', 'N/A')
                        
                        # Try multiple price extraction methods
                        price = 0.0
                        
                        # Method 1: Check price object structure
                        price_data = product_data.get('price', {})
                        if isinstance(price_data, dict):
                            # Try sales price first
                            if 'sales' in price_data:
                                sales_price = price_data['sales']
                                if isinstance(sales_price, dict):
                                    price = float(sales_price.get('value', 0))
                                else:
                                    price = float(sales_price) if sales_price else 0
                            # Try list price as fallback
                            elif 'list' in price_data:
                                list_price = price_data['list']
                                if isinstance(list_price, dict):
                                    price = float(list_price.get('value', 0))
                                else:
                                    price = float(list_price) if list_price else 0
                            # Try raw value
                            elif 'value' in price_data:
                                price = float(price_data['value'])
                        elif isinstance(price_data, (int, float, str)):
                            price = float(price_data) if price_data else 0
                        
                        # Method 2: Look for price in other fields
                        if price == 0.0:
                            for field in ['unitPrice', 'sellingPrice', 'amount', 'cost']:
                                if field in product_data:
                                    try:
                                        price = float(product_data[field])
                                        break
                                    except (ValueError, TypeError):
                                        continue
                        
                        # Method 3: Search page content for price patterns near the SKU
                        if price == 0.0 and sku != 'N/A':
                            # Look for price patterns in the page content around the SKU
                            sku_pattern = re.escape(sku)
                            price_patterns = [
                                rf'{sku_pattern}.*?\$(\d+\.?\d*)',
                                rf'\$(\d+\.?\d*).*?{sku_pattern}',
                                rf'price["\']?\s*:\s*["\']?(\d+\.?\d*)["\']?.*?{sku_pattern}',
                                rf'{sku_pattern}.*?price["\']?\s*:\s*["\']?(\d+\.?\d*)'
                            ]
                            
                            for price_pattern in price_patterns:
                                price_match = re.search(price_pattern, page_content, re.IGNORECASE | re.DOTALL)
                                if price_match:
                                    try:
                                        price = float(price_match.group(1))
                                        self.logger.debug(f"Found price ${price} for SKU {sku} using pattern matching")
                                        break
                                    except (ValueError, IndexError):
                                        continue
                        
                        # Parse weight from product name
                        weight_kg, original_value, original_unit = parse_weight_from_string(product_name)
                        size = standardize_size_format(product_name)
                        
                        # Check availability
                        availability = product_data.get('available', True)
                        if isinstance(availability, str):
                            availability = availability.lower() in ['true', 'yes', 'available', 'instock']
                        
                        # Calculate Canadian import costs
                        cost_breakdown = self._calculate_canadian_costs(price)
                        
                        self.logger.debug(f"Extracted variation: {size} - ${price} (SKU: {sku})")
                        
                        return {
                            'size': size,
                            'price': price,
                            'is_variation_in_stock': bool(availability),
                            'weight_kg': weight_kg,
                            'original_weight_value': original_value,
                            'original_weight_unit': original_unit,
                            'sku': sku,
                            'canadian_costs': cost_breakdown
                        }
                        
                    except json.JSONDecodeError as e:
                        self.logger.debug(f"JSON decode error for pattern {pattern}: {e}")
                        continue
            
            # Fallback to HTML extraction with enhanced price detection
            price_selectors = [
                '.price .value',
                '.product-price',
                '.sales-price',
                '.current-price',
                '[data-price]',
                '.price-current',
                '.price-sales'
            ]
            
            price = 0.0
            for selector in price_selectors:
                price_elem = self.page.locator(selector).first
                if price_elem.count() > 0:
                    price_text = price_elem.text_content()
                    extracted_price = extract_price(price_text)
                    if extracted_price and extracted_price > 0:
                        price = extracted_price
                        break
            
            # Get product title
            title_selectors = ['h1', '.product-title', '.product-name', '.pdp-product-name']
            product_title = ""
            for selector in title_selectors:
                title_elem = self.page.locator(selector).first
                if title_elem.count() > 0:
                    product_title = clean_text(title_elem.text_content())
                    if product_title:
                        break
            
            weight_kg, original_value, original_unit = parse_weight_from_string(product_title)
            size = standardize_size_format(product_title)
            
            # Calculate Canadian import costs
            cost_breakdown = self._calculate_canadian_costs(price)
            
            return {
                'size': size,
                'price': price,
                'is_variation_in_stock': True,
                'weight_kg': weight_kg,
                'original_weight_value': original_value,
                'original_weight_unit': original_unit,
                'sku': 'N/A',
                'canadian_costs': cost_breakdown
            }
                
        except Exception as e:
            self.logger.debug(f"Error extracting variation data: {e}")
        
        return None
    
    def get_politeness_delay(self) -> float:
        """Get delay between requests. Johnny's Seeds is a large commercial site."""
        return 1.5  # 1.5 seconds between requests


def main():
    """Main function to run the Johnny's Seeds scraper."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Scrape microgreens from Johnny\'s Seeds')
    parser.add_argument('--test', action='store_true', help='Run in test mode (limited products)')
    parser.add_argument('--limit', type=int, default=3, help='Number of products to test (default: 3)')
    args = parser.parse_args()
    
    scraper = JohnnySeedsScaper(test_mode=args.test, test_limit=args.limit)
    scraper.run()


if __name__ == "__main__":
    main()