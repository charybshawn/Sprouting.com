#!/usr/bin/env python3
"""
Quick test script to debug Johnny's Seeds variation parsing
"""

import json
import logging
from playwright.sync_api import sync_playwright
from scraper_utils import parse_weight_from_string, standardize_size_format, extract_price, clean_text

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("test_variations")

def test_broccoli_variations():
    """Test variation parsing on the broccoli page"""
    url = "https://www.johnnyseeds.com/vegetables/microgreens/microgreen-vegetables/broccoli-microgreen-seed-2290M.html"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Show browser
        page = browser.new_page()
        
        try:
            logger.info(f"Loading page: {url}")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)  # Wait for JS
            
            # Look for size/weight related elements first
            logger.info("\n--- Looking for size/weight elements ---")
            weight_selectors = [
                'select[data-attribute*="Size"] option',
                'select[name*="size"] option', 
                'select[name*="Size"] option',
                'select[id*="size"] option',
                'select[class*="size"] option',
                '.size-selector option',
                '.weight-selector option',
                'button[data-size]',
                'button[data-weight]',
                '*[data-size]',
                '*[data-weight]',
                # Look for text containing weight units
                '*:has-text("oz")',
                '*:has-text("lb")',
                '*:has-text("pound")',
                '*:has-text("ounce")'
            ]
            
            for selector in weight_selectors:
                logger.info(f"Testing weight selector: {selector}")
                elements = page.locator(selector).all()
                if elements:
                    logger.info(f"Found {len(elements)} elements with {selector}")
                    for i, elem in enumerate(elements[:5]):  # Limit to first 5
                        text = clean_text(elem.text_content())
                        logger.info(f"  Element {i+1}: '{text}'")
            
            # Try generic selectors
            selectors = [
                'select option',
                '.product-options select option',
                'form select option'
            ]
            
            for selector in selectors:
                logger.info(f"\n--- Testing selector: {selector} ---")
                options = page.locator(selector).all()
                logger.info(f"Found {len(options)} options")
                
                for i, option in enumerate(options):
                    text = clean_text(option.text_content())
                    value = option.get_attribute('value') or ''
                    price_attr = option.get_attribute('data-price') or ''
                    logger.info(f"Option {i+1}: text='{text}', value='{value}', price='{price_attr}'")
                    
                    if text and text.lower() not in ['select', 'choose', '']:
                        weight_info = parse_weight_from_string(text)
                        logger.info(f"  Weight parsed: {weight_info}")
                
                if options:
                    break  # Stop after first successful selector
            
            # Also check for JSON-LD data
            logger.info("\n--- Checking for JSON-LD data ---")
            json_scripts = page.locator('script[type="application/ld+json"]').all()
            for i, script in enumerate(json_scripts):
                content = script.text_content()
                if content and 'Product' in content:
                    logger.info(f"JSON-LD script {i+1}: {content[:200]}...")
                    try:
                        data = json.loads(content)
                        if data.get('@type') == 'Product':
                            offers = data.get('offers', [])
                            logger.info(f"Found {len(offers) if isinstance(offers, list) else 1} offers in JSON-LD")
                            if isinstance(offers, dict):
                                offers = [offers]
                            for j, offer in enumerate(offers):
                                logger.info(f"Offer {j+1}: {offer}")
                    except json.JSONDecodeError as e:
                        logger.warning(f"Could not parse JSON-LD: {e}")
            
            # Check for any product JSON
            logger.info("\n--- Checking for product JSON ---") 
            all_scripts = page.locator('script').all()
            for i, script in enumerate(all_scripts):
                content = script.text_content()
                if content and ('variants' in content or 'variations' in content):
                    logger.info(f"Script {i+1} contains 'variants': {content[:300]}...")
            
            # Don't wait for input in automated mode
            page.wait_for_timeout(2000)
            
        finally:
            browser.close()

if __name__ == "__main__":
    test_broccoli_variations()