#!/usr/bin/env python3
"""
True Leaf Market scraper using Playwright.
Falls back to web scraping since JSON endpoints are disabled.
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Any
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from seed_name_parser import parse_with_botanical_field_names
from scraper_utils import (
    setup_logging, parse_weight_from_string, standardize_size_format,
    is_organic_product, calculate_canadian_import_costs, make_absolute_url,
    ScraperError, NetworkError
)

# --- Constants ---
BASE_URL = "https://trueleafmarket.com"
OUTPUT_DIR = "./scraper_data/json_files/trueleaf_market"
SUPPLIER_NAME = "trueleafmarket_com"
CURRENCY_CODE = "USD"

# Collections to scrape (most relevant for microgreens/sprouting)
# Note: Try both regular and atom URLs since availability may vary
TARGET_COLLECTIONS = [
    "micro-greens-planting-seed",
    "wholesale-sprouting-seed"
]

# --- Setup Logger ---
logger = setup_logging("trueleafmarket_scraper")

class TrueLeafMarketScraper:
    """Playwright-based scraper for True Leaf Market"""
    
    def __init__(self, test_mode: bool = False, headless: bool = True):
        self.test_mode = test_mode
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.page = None
        
    def __enter__(self):
        self.playwright = sync_playwright().start()
        
        # Use Chrome with stealth
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox'
            ]
        )
        
        context = self.browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1366, 'height': 768},
            locale='en-US',
            timezone_id='America/Toronto',
            extra_http_headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
        )
        
        self.page = context.new_page()
        
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
    
    def extract_product_links(self, collection_url: str) -> List[Dict[str, Any]]:
        """Extract product links from a collection page"""
        logger.info(f"Opening page: {collection_url}")
        
        try:
            # Try to visit main site first and behave like human
            logger.info("First visiting main site...")
            self.page.goto(BASE_URL, timeout=30000, wait_until="networkidle")
            time.sleep(3)
            
            # Simulate human behavior - scroll a bit
            self.page.evaluate("window.scrollTo(0, 200)")
            time.sleep(1)
            
            # Now navigate to collection page
            logger.info(f"Now navigating to collection: {collection_url}")
            self.page.goto(collection_url, timeout=20000, wait_until="domcontentloaded")
            time.sleep(5)
            
            # Handle infinite scroll (no buttons, just scroll)
            logger.info("Loading all products via infinite scroll...")
            self._scroll_to_load_all_products()
            
            # Check page content and log details
            page_content = self.page.content()
            title = self.page.title()
            url = self.page.url
            
            logger.info(f"Page title: '{title}'")
            logger.info(f"Final URL: {url}")
            logger.info(f"Page content length: {len(page_content)} characters")
            
            # Save page content for debugging
            with open('trueleaf_debug_content.html', 'w', encoding='utf-8') as f:
                f.write(page_content)
            logger.info("Page content saved to trueleaf_debug_content.html")
            
            # Check for actual 502 error page (not just "502" in regular content like "Half a million")
            if ('502 Bad Gateway' in page_content or 
                '<title>502 Bad Gateway</title>' in page_content or
                'HTTP Error 502' in page_content):
                logger.error("Page content contains 502 Bad Gateway error")
                logger.info(f"First 500 chars: {page_content[:500]}")
                return []
            
            # Look for product links directly
            logger.info("Looking for product links...")
            product_links = self.page.locator('a[href*="/products/"]').all()
            logger.info(f"Found {len(product_links)} product links")
            
            # Debug: let's see what URLs we found
            for i, link in enumerate(product_links[:5]):  # Show first 5
                href = link.get_attribute('href')
                logger.info(f"Product link {i+1}: {href}")
            
            if not product_links:
                logger.warning("No product links found")
                return []
            
            products = []
            seen_urls = set()  # Track URLs to avoid duplicates
            
            for link_element in product_links:
                try:
                    href = link_element.get_attribute('href')
                    if not href:
                        continue
                    
                    # Skip review links and other fragments
                    if '#review' in href or '#' in href:
                        logger.debug(f"Skipping fragment URL: {href}")
                        continue
                        
                    product_url = make_absolute_url(href, BASE_URL)
                    
                    # Skip if we've already seen this URL
                    if product_url in seen_urls:
                        logger.debug(f"Skipping duplicate URL: {product_url}")
                        continue
                    
                    # Extract title from the p tag within the link
                    title_element = link_element.locator('p').first
                    if title_element.count() > 0:
                        title_text = title_element.text_content().strip()
                    else:
                        # Fallback to link text content
                        title_text = link_element.text_content().strip()
                    
                    if not title_text:
                        continue
                    
                    # Skip obvious non-products
                    skip_terms = [
                        "reviews", "review", "gift card", "gift", "rating", 
                        "stars", "write a review", "read reviews", "view all"
                    ]
                    if any(term in title_text.lower() for term in skip_terms):
                        logger.debug(f"Skipping non-product: '{title_text}'")
                        continue
                    
                    # Skip if title is too short or looks like UI text
                    if len(title_text.strip()) < 5:
                        logger.debug(f"Skipping short title: '{title_text}'")
                        continue
                    
                    # Must contain seed-related terms
                    seed_terms = ["seed", "microgreen", "sprout", "plant", "organic", "heirloom"]
                    if not any(term in title_text.lower() for term in seed_terms):
                        logger.debug(f"Skipping non-seed product: '{title_text}'")
                        continue
                    
                    # Parse botanical info
                    parsed_info = parse_with_botanical_field_names(title_text)
                    if parsed_info['common_name'] == "N/A":
                        logger.debug(f"Skipping '{title_text}' - no matching common name")
                        continue
                    
                    # Add to seen URLs and products list
                    seen_urls.add(product_url)
                    products.append({
                        'title': title_text,
                        'url': product_url,
                        'common_name': parsed_info['common_name'],
                        'cultivar_name': parsed_info['cultivar_name'],
                        'organic': is_organic_product(title_text)
                    })
                    
                except Exception as e:
                    logger.warning(f"Error processing product tile: {e}")
                    continue
            
            logger.info(f"Extracted {len(products)} valid products")
            return products
            
        except Exception as e:
            logger.error(f"Error opening page {collection_url}: {e}")
            return []
    
    def _scroll_to_load_all_products(self):
        """Handle infinite scroll by scrolling to bottom repeatedly"""
        max_attempts = 10
        attempts = 0
        
        logger.info("Starting infinite scroll...")
        
        while attempts < max_attempts:
            # Get current page height
            current_height = self.page.evaluate("document.body.scrollHeight")
            
            # Scroll to bottom
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            # Wait for content to load
            time.sleep(3)
            
            # Check if new content loaded
            new_height = self.page.evaluate("document.body.scrollHeight")
            
            if new_height > current_height:
                logger.info(f"Infinite scroll loaded more content (height: {current_height} -> {new_height})")
                attempts += 1
                continue
            else:
                logger.info("No more content to load via infinite scroll")
                break
                
        logger.info(f"Finished infinite scroll after {attempts} attempts")
    
    def scrape_product_details(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """Scrape detailed product information"""
        logger.info(f"Scraping details for: {product['title']}")
        
        try:
            self.page.goto(product['url'], timeout=15000, wait_until="domcontentloaded")
            time.sleep(2)
            
            # Debug: Save page content to see structure
            page_content = self.page.content()
            logger.debug(f"Product page content length: {len(page_content)}")
            
            # Try to extract JSON-LD product data
            json_ld_variations = self._extract_json_ld_variations()
            logger.info(f"JSON-LD found {len(json_ld_variations)} variations")
            if json_ld_variations:
                product_data = product.copy()
                product_data['variations'] = json_ld_variations
                product_data['is_in_stock'] = any(var['is_variation_in_stock'] for var in json_ld_variations)
                # Still extract info sections
                basic_info = self._extract_info_section("Basic Info")
                growing_info = self._extract_info_section("Growing Info")
                product_data['basic_info'] = basic_info
                product_data['growing_info'] = growing_info
                return product_data
            
            # Fallback to HTML parsing
            html_variations = self._parse_html_variations()
            logger.info(f"HTML parsing found {len(html_variations)} variations")
            
            # Always try basic price extraction too (since HTML parsing might miss actual variations)
            logger.info("Trying basic price extraction for True Leaf Market structure...")
            basic_variations = self._extract_basic_price_info()
            logger.info(f"Basic price extraction found {len(basic_variations)} variations")
            
            # Use basic variations if they found more than HTML parsing
            if len(basic_variations) > len(html_variations):
                logger.info("Using basic price extraction results (found more variations)")
                html_variations = basic_variations
            elif not html_variations and basic_variations:
                logger.info("Using basic price extraction results (HTML found none)")
                html_variations = basic_variations
            
            product_data = product.copy()
            product_data['variations'] = html_variations
            product_data['is_in_stock'] = any(var['is_variation_in_stock'] for var in html_variations)
            
            # Extract additional info sections
            basic_info = self._extract_structured_basic_info()
            growing_info = self._extract_info_section("Growing Info")
            logger.info(f"Basic info extracted: {len(basic_info.get('raw_text', ''))} chars")
            logger.info(f"Growing info extracted: {len(growing_info)} chars")
            
            product_data['basic_info'] = basic_info
            product_data['growing_info'] = growing_info
            
            return product_data
            
        except Exception as e:
            logger.error(f"Error scraping product details for {product['url']}: {e}")
            # Return minimal product data
            cost_breakdown = calculate_canadian_import_costs(
                base_price=0.0,
                source_currency="USD",
                province="BC",
                commercial_use=True
            )
            
            return {
                **product,
                'variations': [{
                    'size': 'Error - could not parse',
                    'price': 0.0,
                    'is_variation_in_stock': False,
                    'weight_kg': None,
                    'original_weight_value': None,
                    'original_weight_unit': None,
                    'sku': 'N/A',
                    'canadian_costs': cost_breakdown
                }],
                'is_in_stock': False
            }
    
    def _extract_json_ld_variations(self) -> List[Dict[str, Any]]:
        """Extract variations from JSON-LD structured data"""
        try:
            json_ld_scripts = self.page.locator('script[type="application/ld+json"]').all()
            for script in json_ld_scripts:
                content = script.text_content()
                if content and 'Product' in content:
                    data = json.loads(content)
                    if isinstance(data, dict) and data.get('@type') == 'Product':
                        return self._parse_json_ld_offers(data)
        except Exception as e:
            logger.debug(f"Error extracting JSON-LD data: {e}")
        return []
    
    def _parse_json_ld_offers(self, product_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse JSON-LD offers into variations"""
        variations = []
        offers = product_data.get('offers', [])
        if isinstance(offers, dict):
            offers = [offers]
        
        for offer in offers:
            price = float(offer.get('price', 0))
            sku = offer.get('sku', 'N/A')
            name = offer.get('name', product_data.get('name', ''))
            
            # Parse weight
            weight_kg, original_value, original_unit = parse_weight_from_string(name)
            
            # Skip packets
            if 'packet' in name.lower():
                continue
            
            # Check availability
            availability = offer.get('availability', '').lower()
            is_in_stock = 'instock' in availability
            
            # Calculate costs
            cost_breakdown = calculate_canadian_import_costs(
                base_price=price,
                source_currency="USD",
                province="BC",
                min_shipping=12.50,
                max_shipping=125.00,
                brokerage_fee=17.50,
                commercial_use=True
            )
            
            variations.append({
                'size': standardize_size_format(name),
                'price': price,
                'is_variation_in_stock': is_in_stock,
                'weight_kg': weight_kg,
                'original_weight_value': original_value,
                'original_weight_unit': original_unit,
                'sku': sku,
                'canadian_costs': cost_breakdown
            })
        
        return variations
    
    def _parse_html_variations(self) -> List[Dict[str, Any]]:
        """Parse variations from HTML as fallback"""
        variations = []
        
        try:
            # Try to find variant selector (common in Shopify)
            variant_selectors = [
                'select[name*="id"] option',
                'select[data-variant] option',
                '.product-variants option',
                '.variant-selector option'
            ]
            
            for selector in variant_selectors:
                options = self.page.locator(selector).all()
                if options:
                    for option in options:
                        option_text = option.text_content().strip()
                        option_value = option.get_attribute('value')
                        
                        if not option_text or option_text.lower() in ['select', 'choose']:
                            continue
                        
                        # Parse weight
                        weight_kg, original_value, original_unit = parse_weight_from_string(option_text)
                        
                        # Skip packets
                        if 'packet' in option_text.lower():
                            continue
                        
                        # Get price (might be in data attribute)
                        price = 0.0
                        price_attr = option.get_attribute('data-price')
                        if price_attr:
                            try:
                                price = float(price_attr) / 100  # Shopify stores in cents
                            except ValueError:
                                pass
                        
                        # If no price from option, try to get base price
                        if price == 0.0:
                            price_elem = self.page.locator('.price, .product-price').first
                            if price_elem.count() > 0:
                                price_text = price_elem.text_content()
                                price_match = __import__('re').search(r'[\d,]+\.?\d*', price_text.replace('$', ''))
                                if price_match:
                                    price = float(price_match.group().replace(',', ''))
                        
                        is_disabled = option.get_attribute('disabled') is not None
                        
                        # Calculate costs
                        cost_breakdown = calculate_canadian_import_costs(
                            base_price=price,
                            source_currency="USD",
                            province="BC",
                            min_shipping=12.50,
                            max_shipping=125.00,
                            brokerage_fee=17.50,
                            commercial_use=True
                        )
                        
                        variations.append({
                            'size': standardize_size_format(option_text),
                            'price': price,
                            'is_variation_in_stock': not is_disabled,
                            'weight_kg': weight_kg,
                            'original_weight_value': original_value,
                            'original_weight_unit': original_unit,
                            'sku': option_value or 'N/A',
                            'canadian_costs': cost_breakdown
                        })
                    
                    if variations:
                        break
            
            # If no variants found, create single default variation
            if not variations:
                price_elem = self.page.locator('.price, .product-price').first
                price = 0.0
                if price_elem.count() > 0:
                    price_text = price_elem.text_content()
                    price_match = __import__('re').search(r'[\d,]+\.?\d*', price_text.replace('$', ''))
                    if price_match:
                        price = float(price_match.group().replace(',', ''))
                
                # Check if sold out
                sold_out = self.page.locator('.sold-out, .out-of-stock').count() > 0
                
                cost_breakdown = calculate_canadian_import_costs(
                    base_price=price,
                    source_currency="USD",
                    province="BC",
                    min_shipping=12.50,
                    max_shipping=125.00,
                    brokerage_fee=17.50,
                    commercial_use=True
                )
                
                variations.append({
                    'size': 'Standard',
                    'price': price,
                    'is_variation_in_stock': not sold_out,
                    'weight_kg': None,
                    'original_weight_value': None,
                    'original_weight_unit': None,
                    'sku': 'N/A',
                    'canadian_costs': cost_breakdown
                })
        
        except Exception as e:
            logger.error(f"Error parsing HTML variations: {e}")
        
        return variations
    
    def _extract_basic_price_info(self) -> List[Dict[str, Any]]:
        """Extract basic price info using the actual True Leaf Market structure"""
        variations = []
        
        try:
            # Look for variant labels containing Size radio inputs
            # <label><input type="radio" name="option[Size]" value="1 oz">...</label>
            
            variant_containers = self.page.locator('label:has(input[name*="Size"])').all()
            logger.info(f"Found {len(variant_containers)} variant labels")
            
            if not variant_containers:
                # Fallback to grid containers directly
                variant_containers = self.page.locator('div.grid.min-w-\\[130px\\]').all()
                logger.info(f"Fallback: Found {len(variant_containers)} grid containers")
                
            if not variant_containers:
                # Try another fallback - look for any elements with strong tags and prices
                variant_containers = self.page.locator('div:has(strong):has-text("$")').all()
                logger.info(f"Second fallback: Found {len(variant_containers)} containers with strong and $")
            for i, container in enumerate(variant_containers):
                try:
                    logger.info(f"Processing variant container {i+1}")
                    
                    # Extract size from radio input value first, then fallback to <strong> tag
                    size_text = ""
                    input_elem = container.locator('input[name*="Size"]').first
                    if input_elem.count() > 0:
                        size_text = input_elem.get_attribute('value') or ""
                        logger.info(f"Found input value: {size_text}")
                    
                    # Fallback to <strong> tag if no input value
                    if not size_text:
                        size_elem = container.locator('strong').first
                        if size_elem.count() > 0:
                            size_text = size_elem.text_content().strip()
                            logger.info(f"Found strong text: {size_text}")
                    
                    if not size_text:
                        logger.info("No size text found, skipping")
                        continue
                    
                    # Extract price from the nested div structure
                    price_elem = container.locator('div.flex.justify-between div').first
                    if price_elem.count() == 0:
                        logger.info("No price element found")
                        continue
                        
                    price_text = price_elem.text_content().strip()
                    logger.info(f"Found price text: {price_text}")
                    if not price_text or '$' not in price_text:
                        logger.info("Price text missing or no $ symbol")
                        continue
                    
                    # Parse price
                    import re
                    price_match = re.search(r'\$?(\d+\.?\d*)', price_text.replace(',', ''))
                    if not price_match:
                        logger.info("Could not parse price from text")
                        continue
                        
                    price = float(price_match.group(1))
                    logger.info(f"Parsed price: ${price}")
                    
                    # Parse weight from size text
                    weight_kg, original_value, original_unit = parse_weight_from_string(size_text)
                    
                    # Skip packets
                    if 'packet' in size_text.lower():
                        continue
                    
                    # Check if in stock (you might need to adjust this selector)
                    is_in_stock = True  # Default to true, adjust if there's an out-of-stock indicator
                    
                    cost_breakdown = calculate_canadian_import_costs(
                        base_price=price,
                        source_currency="USD",
                        province="BC",
                        min_shipping=12.50,
                        max_shipping=125.00,
                        brokerage_fee=17.50,
                        commercial_use=True
                    )
                    
                    variations.append({
                        'size': standardize_size_format(size_text),
                        'price': price,
                        'is_variation_in_stock': is_in_stock,
                        'weight_kg': weight_kg,
                        'original_weight_value': original_value,
                        'original_weight_unit': original_unit,
                        'sku': 'N/A',  # You might be able to extract this from data attributes
                        'canadian_costs': cost_breakdown
                    })
                    
                    logger.debug(f"Extracted variation: {size_text} = ${price}")
                    
                except Exception as e:
                    logger.debug(f"Error processing price container: {e}")
                    continue
            
            logger.debug(f"Extracted {len(variations)} variations from price containers")
            
        except Exception as e:
            logger.error(f"Error extracting basic price info: {e}")
        
        return variations
    
    def _extract_structured_basic_info(self) -> Dict[str, str]:
        """Extract and structure basic info into sub-fields"""
        basic_info_text = self._extract_info_section("Basic Info")
        
        # Parse the basic info into structured fields
        structured_info = {
            "latin_name": "",
            "microgreen_color": "",
            "microgreen_flavor": "",
            "microgreen_texture": "",
            "nutrients": "",
            "other_names": "",
            "raw_text": basic_info_text
        }
        
        if basic_info_text:
            # The text comes as one concatenated string, so we need to parse it differently
            import re
            
            # Extract Latin Name
            latin_match = re.search(r'Latin Name:\s*([^A-Z]*?)(?=[A-Z][a-z]+\s*[A-Z]|$)', basic_info_text)
            if latin_match:
                structured_info['latin_name'] = latin_match.group(1).strip()
            
            # Extract Microgreen Color
            color_match = re.search(r'Microgreen Color:\s*([^A-Z]*?)(?=Microgreen [A-Z]|$)', basic_info_text)
            if color_match:
                structured_info['microgreen_color'] = color_match.group(1).strip()
            
            # Extract Microgreen Flavor
            flavor_match = re.search(r'Microgreen Flavo[u]?r:\s*([^A-Z]*?)(?=Microgreen [A-Z]|$)', basic_info_text)
            if flavor_match:
                structured_info['microgreen_flavor'] = flavor_match.group(1).strip()
            
            # Extract Microgreen Texture
            texture_match = re.search(r'Microgreen Texture:\s*([^A-Z]*?)(?=Nutrients|$)', basic_info_text)
            if texture_match:
                structured_info['microgreen_texture'] = texture_match.group(1).strip()
            
            # Extract Nutrients
            nutrients_match = re.search(r'Nutrients:\s*([^A-Z]*?)(?=Other Name|$)', basic_info_text)
            if nutrients_match:
                structured_info['nutrients'] = nutrients_match.group(1).strip()
            
            # Extract Other Names
            other_match = re.search(r'Other Name[s]?[^:]*:\s*([^A-Z]*?)(?=Microgreen|$)', basic_info_text)
            if other_match:
                structured_info['other_names'] = other_match.group(1).strip()
        
        return structured_info
    
    def _extract_info_section(self, section_title: str) -> str:
        """Extract content from Basic Info or Growing Info sections"""
        try:
            # Try multiple ways to find the header
            header = None
            
            # Method 1: Exact text match with font-serif class
            header_selector = f'h3.font-serif:has-text("{section_title}")'
            header = self.page.locator(header_selector).first
            
            if header.count() == 0:
                # Method 2: Any h3 with the text
                header = self.page.locator(f'h3:has-text("{section_title}")').first
                
            if header.count() == 0:
                # Method 3: Look for text content containing the title
                all_h3s = self.page.locator('h3').all()
                for h3 in all_h3s:
                    if section_title.lower() in h3.text_content().lower():
                        header = h3
                        break
                        
            if not header or header.count() == 0:
                # Debug: show what h3 headers are actually on the page
                all_h3s = self.page.locator('h3').all()
                h3_texts = []
                for h3 in all_h3s[:5]:  # Show first 5
                    try:
                        h3_texts.append(f"'{h3.text_content().strip()}'")
                    except:
                        pass
                logger.debug(f"No '{section_title}' header found. Available h3s: {', '.join(h3_texts)}")
                return ""
            
            # Get all content after the header until the next h3 or end of section
            content_parts = []
            
            # Start from the header and look for following siblings
            current_element = header
            
            # Try to get the parent container and find content after the header
            parent = header.locator('..').first
            if parent.count() > 0:
                # Look for content elements after the header within the parent
                content_elements = parent.locator('p, div, ul, li').all()
                
                for elem in content_elements:
                    try:
                        text = elem.text_content().strip()
                        if text and text != section_title:
                            # Stop if we hit another section header
                            if any(stop_phrase in text for stop_phrase in ["Basic Info", "Growing Info", "Nutritional Info"]):
                                break
                            content_parts.append(text)
                    except Exception as e:
                        logger.debug(f"Error processing content element: {e}")
                        continue
            
            # If we didn't find content in parent, try a different approach
            if not content_parts:
                # Look for content in the next sibling elements
                try:
                    # Use JavaScript to get following siblings until next h3
                    script = f"""
                    (() => {{
                        const header = document.querySelector('h3.font-serif');
                        if (!header || !header.textContent.includes('{section_title}')) return '';
                        
                        let content = [];
                        let sibling = header.nextElementSibling;
                        
                        while (sibling) {{
                            if (sibling.tagName === 'H3') break;
                            if (sibling.textContent.trim()) {{
                                content.push(sibling.textContent.trim());
                            }}
                            sibling = sibling.nextElementSibling;
                        }}
                        
                        return content.join('\\n');
                    }})();
                    """
                    
                    js_content = self.page.evaluate(script)
                    if js_content:
                        content_parts = [js_content]
                        
                except Exception as e:
                    logger.debug(f"JavaScript extraction failed: {e}")
            
            result = '\n'.join(content_parts).strip()
            logger.debug(f"Extracted {len(result)} characters for '{section_title}'")
            return result
            
        except Exception as e:
            logger.debug(f"Error extracting '{section_title}': {e}")
            return ""
    
    def _extract_from_atom_feed(self, page_content: str) -> List[Dict[str, Any]]:
        """Extract products from XML Atom feed"""
        products = []
        try:
            import xml.etree.ElementTree as ET
            
            # Parse XML content
            root = ET.fromstring(page_content)
            
            # Handle namespaces
            namespaces = {
                'atom': 'http://www.w3.org/2005/Atom',
                '': 'http://www.w3.org/2005/Atom'
            }
            
            # Find all entries (products)
            entries = root.findall('.//entry', namespaces)
            logger.info(f"Found {len(entries)} entries in atom feed")
            
            for entry in entries:
                try:
                    # Extract product title
                    title_elem = entry.find('title', namespaces)
                    title = title_elem.text if title_elem is not None else ""
                    
                    # Extract product URL
                    link_elem = entry.find('link[@rel="alternate"]', namespaces)
                    if link_elem is None:
                        link_elem = entry.find('link', namespaces)
                    
                    url = link_elem.get('href') if link_elem is not None else ""
                    if url and not url.startswith('http'):
                        url = make_absolute_url(url, BASE_URL)
                    
                    if not title or not url:
                        continue
                    
                    # Parse botanical information
                    parsed_info = parse_with_botanical_field_names(title)
                    if parsed_info['common_name'] == "N/A":
                        logger.debug(f"Skipping '{title}' - no matching common name")
                        continue
                    
                    products.append({
                        'title': title,
                        'url': url,
                        'common_name': parsed_info['common_name'],
                        'cultivar_name': parsed_info['cultivar_name'],
                        'organic': is_organic_product(title)
                    })
                    
                except Exception as e:
                    logger.warning(f"Error processing atom entry: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error parsing atom feed: {e}")
        
        logger.info(f"Extracted {len(products)} products from atom feed")
        return products
    
    def scrape_all_collections(self) -> List[Dict[str, Any]]:
        """Scrape all target collections"""
        all_products = []
        
        # Just test the first collection
        collection_handle = TARGET_COLLECTIONS[0]
        collection_url = f"{BASE_URL}/collections/{collection_handle}"
        logger.info(f"Testing collection: {collection_url}")
        
        try:
            # Extract product links from collection page
            basic_products = self.extract_product_links(collection_url)
            
            if basic_products:
                logger.info(f"Found {len(basic_products)} products, now scraping details...")
                
                # Limit products in test mode
                products_to_scrape = basic_products[:5] if self.test_mode else basic_products
                logger.info(f"Scraping details for {len(products_to_scrape)} products")
                
                # Scrape detailed information for each product
                for i, product in enumerate(products_to_scrape, 1):
                    logger.info(f"Scraping product {i}/{len(products_to_scrape)}: {product['title']}")
                    try:
                        detailed_product = self.scrape_product_details(product)
                        all_products.append(detailed_product)
                    except Exception as e:
                        logger.error(f"Error scraping product {product['url']}: {e}")
                        # Add basic product data if detailed scraping fails
                        all_products.append(product)
                        continue
            else:
                logger.warning("No products found")
                
        except Exception as e:
            logger.error(f"Error processing collection {collection_handle}: {e}")
        
        return all_products
    
    def save_products_to_json(self, products: List[Dict[str, Any]], scrape_duration: float):
        """Save products to JSON file"""
        if not products:
            logger.warning("No products to save")
            return
        
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        timestamp = datetime.now()
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp_str}.json"
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        data = {
            "timestamp": timestamp.isoformat(),
            "scrape_duration_seconds": round(scrape_duration, 2),
            "source_site": BASE_URL,
            "currency_code": CURRENCY_CODE,
            "product_count": len(products),
            "data": products
        }
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            os.chmod(filepath, 0o664)
            logger.info(f"Saved {len(products)} products to {filepath}")
            
        except Exception as e:
            logger.error(f"Error saving products: {e}")
    
    def run(self):
        """Main scraper execution"""
        start_time = time.time()
        logger.info(f"Starting True Leaf Market scraper (test_mode: {self.test_mode}, headless: {self.headless})")
        
        with self:
            try:
                products = self.scrape_all_collections()
                scrape_duration = time.time() - start_time
                
                if products:
                    self.save_products_to_json(products, scrape_duration)
                    logger.info(f"Scraping completed in {scrape_duration:.2f} seconds")
                else:
                    logger.warning("No products were scraped")
                    
            except Exception as e:
                logger.error(f"Scraper failed: {e}")
                raise


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Scrape True Leaf Market seed products')
    parser.add_argument('--test', action='store_true', help='Run in test mode (limited products)')
    parser.add_argument('--headless', action='store_true', default=True, help='Run browser in headless mode (default: True)')
    parser.add_argument('--no-headless', dest='headless', action='store_false', help='Run browser in visible mode')
    args = parser.parse_args()
    
    scraper = TrueLeafMarketScraper(test_mode=args.test, headless=args.headless)
    scraper.run()


if __name__ == "__main__":
    main()