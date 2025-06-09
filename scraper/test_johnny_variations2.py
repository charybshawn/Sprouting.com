#!/usr/bin/env python3
"""
Targeted test to find the actual weight variations on Johnny's Seeds
"""

import json
import logging
from playwright.sync_api import sync_playwright
from scraper_utils import parse_weight_from_string, standardize_size_format, extract_price, clean_text

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("test_variations2")

def test_broccoli_variations():
    """Test variation parsing on the broccoli page with more specific targeting"""
    url = "https://www.johnnyseeds.com/vegetables/microgreens/microgreen-vegetables/broccoli-microgreen-seed-2290M.html"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Show browser
        page = browser.new_page()
        
        try:
            logger.info(f"Loading page: {url}")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)  # Wait longer for JS
            
            # Look for specific weight-related text
            logger.info("\n--- Looking for visible weight text ---")
            page_text = page.content()
            
            weight_terms = ['1 oz', '1/4 pound', '1 pound', '5 pounds', '25 pounds', 
                           '1oz', '4oz', '1lb', '5lb', '25lb']
            
            for term in weight_terms:
                if term.lower() in page_text.lower():
                    logger.info(f"Found '{term}' in page content")
                    
                    # Try to find elements containing this text
                    elements = page.locator(f'*:has-text("{term}")').all()
                    logger.info(f"  Found {len(elements)} elements containing '{term}'")
                    
                    for i, elem in enumerate(elements[:3]):  # First 3 elements
                        text = clean_text(elem.text_content())
                        tag = elem.evaluate('el => el.tagName')
                        classes = elem.get_attribute('class') or ''
                        logger.info(f"    Element {i+1} ({tag}, class='{classes}'): '{text[:100]}...'")
            
            # Look for product forms and add-to-cart areas
            logger.info("\n--- Looking for product forms ---")
            forms = page.locator('form').all()
            logger.info(f"Found {len(forms)} forms")
            
            for i, form in enumerate(forms):
                action = form.get_attribute('action') or ''
                if 'cart' in action.lower() or 'add' in action.lower():
                    logger.info(f"Form {i+1} (action='{action}'):")
                    
                    # Look for all inputs and selects in this form
                    inputs = form.locator('input, select').all()
                    for j, input_elem in enumerate(inputs):
                        tag = input_elem.evaluate('el => el.tagName')
                        name = input_elem.get_attribute('name') or ''
                        type_attr = input_elem.get_attribute('type') or ''
                        logger.info(f"  {tag} {j+1}: name='{name}', type='{type_attr}'")
                        
                        if tag == 'SELECT':
                            options = input_elem.locator('option').all()
                            logger.info(f"    {len(options)} options:")
                            for k, opt in enumerate(options[:5]):
                                opt_text = clean_text(opt.text_content())
                                opt_value = opt.get_attribute('value') or ''
                                logger.info(f"      Option {k+1}: '{opt_text}' (value='{opt_value}')")
            
            # Look for data attributes that might contain product info
            logger.info("\n--- Looking for data attributes ---")
            data_elements = page.locator('[data-product], [data-variant], [data-price], [data-size]').all()
            logger.info(f"Found {len(data_elements)} elements with data attributes")
            
            for i, elem in enumerate(data_elements):
                attrs = elem.evaluate('''el => {
                    const attrs = {};
                    for (let attr of el.attributes) {
                        if (attr.name.startsWith('data-')) {
                            attrs[attr.name] = attr.value;
                        }
                    }
                    return attrs;
                }''')
                logger.info(f"Element {i+1}: {attrs}")
            
            # Try clicking on different areas to see if variations appear
            logger.info("\n--- Trying to interact with elements ---")
            
            # Look for buttons that might reveal options
            buttons = page.locator('button').all()
            for i, btn in enumerate(buttons[:5]):
                btn_text = clean_text(btn.text_content())
                logger.info(f"Button {i+1}: '{btn_text}'")
                
                if any(word in btn_text.lower() for word in ['size', 'weight', 'option', 'select']):
                    logger.info(f"  Clicking button: '{btn_text}'")
                    try:
                        btn.click(timeout=2000)
                        page.wait_for_timeout(1000)
                        logger.info(f"  Clicked successfully")
                    except Exception as e:
                        logger.info(f"  Click failed: {e}")
            
            page.wait_for_timeout(2000)
            
        finally:
            browser.close()

if __name__ == "__main__":
    test_broccoli_variations()