#!/usr/bin/env python3
import asyncio
from playwright.async_api import async_playwright
import json
import os
import argparse

class SelectorHelper:
    def __init__(self, headless=False):
        self.headless = headless
        self.selectors = {
            "login_page": {
                "email_input": 'input#username',
                "password_input": 'input#password',
                "submit_button": 'button[name="login"]',
                "login_success_indicator": '.woocommerce-MyAccount-navigation, a.woocommerce-MyAccount-navigation-link--customer-logout'
            },
            "category_page": {
                "product_links": 'li.product a.woocommerce-LoopProduct-link',
                "pagination": '.woocommerce-pagination',
                "page_numbers": '.woocommerce-pagination .page-numbers:not(.next):not(.prev)'
            },
            "product_page": {
                "product_title": 'h1.product_title',
                "product_description": 'div.woocommerce-product-details__short-description',
                "product_variations_dropdown": 'table.variations select',
                "product_variations_options": 'table.variations select option',
                "product_variations_radio": '.variation-radios input',
                "product_price": '.woocommerce-variation-price .price, p.price .woocommerce-Price-amount',
                "growing_instructions": '.product-growing-instructions, #tab-description'
            }
        }
        
    async def run(self, url):
        """Run the selector helper on a specified URL"""
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await context.new_page()
            
            # Navigate to the URL
            print(f"Navigating to {url}...")
            await page.goto(url)
            await page.wait_for_load_state("networkidle")
            
            # Determine what type of page we're on
            page_type = self.detect_page_type(url)
            
            if page_type:
                print(f"Detected page type: {page_type}")
                await self.verify_selectors(page, page_type)
            else:
                print("Unknown page type. Please specify if this is a 'login_page', 'category_page', or 'product_page'")
                page_type = input("Page type: ")
                if page_type in self.selectors:
                    await self.verify_selectors(page, page_type)
            
            # Interactive selector finder
            print("\n=== Interactive Selector Finder ===")
            print("Enter CSS selectors to test them, or type 'q' to quit")
            print("Example: .product-title")
            
            while True:
                selector = input("\nEnter selector (q to quit): ")
                if selector.lower() == 'q':
                    break
                    
                try:
                    elements = await page.query_selector_all(selector)
                    if elements:
                        print(f"Found {len(elements)} elements!")
                        for i, element in enumerate(elements[:5]):  # Show first 5
                            text = await element.text_content()
                            text = text.strip() if text else ""
                            attrs = await self.get_element_attributes(element)
                            print(f"  {i+1}. Text: '{text[:50]}{'...' if len(text) > 50 else ''}', Attributes: {attrs}")
                        
                        if len(elements) > 5:
                            print(f"  ... and {len(elements) - 5} more")
                            
                        # Ask if this selector should be saved
                        save = input("Save this selector? (y/n): ")
                        if save.lower() == 'y':
                            name = input("Name for this selector: ")
                            if page_type in self.selectors:
                                self.selectors[page_type][name] = selector
                                print(f"Saved '{name}': '{selector}' for {page_type}")
                    else:
                        print("No elements found with this selector")
                except Exception as e:
                    print(f"Error: {str(e)}")
            
            # Save updated selectors
            self.save_selectors()
            
            await browser.close()
    
    def detect_page_type(self, url):
        """Try to detect the page type from the URL"""
        if '/my-account/' in url or '/login' in url:
            return 'login_page'
        elif '/product/' in url or '/products/' in url:
            return 'product_page'
        elif any(category in url for category in ['/product-category/', '/collections/', '/microgreens', '/sprouting-seeds', '/all-seeds']):
            return 'category_page'
        return None
    
    async def verify_selectors(self, page, page_type):
        """Verify existing selectors for the page type"""
        print(f"\n=== Verifying selectors for {page_type} ===")
        
        for name, selector in self.selectors[page_type].items():
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    print(f"✓ {name}: '{selector}' - Found {len(elements)} elements")
                    
                    # Show a preview of the first element
                    element = elements[0]
                    text = await element.text_content()
                    text = text.strip() if text else ""
                    print(f"  Preview: '{text[:50]}{'...' if len(text) > 50 else ''}'")
                    
                    # Ask if the selector should be updated
                    update = input(f"  Update selector for '{name}'? (y/n): ")
                    if update.lower() == 'y':
                        new_selector = input(f"  New selector for '{name}' (current: '{selector}'): ")
                        if new_selector:
                            self.selectors[page_type][name] = new_selector
                            print(f"  Updated '{name}' to '{new_selector}'")
                else:
                    print(f"✗ {name}: '{selector}' - No elements found")
                    
                    # Ask for a new selector
                    new_selector = input(f"  New selector for '{name}' (current: '{selector}'): ")
                    if new_selector:
                        self.selectors[page_type][name] = new_selector
                        print(f"  Updated '{name}' to '{new_selector}'")
            except Exception as e:
                print(f"✗ {name}: '{selector}' - Error: {str(e)}")
    
    async def get_element_attributes(self, element):
        """Get all attributes of an element"""
        attrs = {}
        for attr in ['id', 'class', 'name', 'value', 'href', 'src']:
            value = await element.get_attribute(attr)
            if value:
                attrs[attr] = value
        return attrs
    
    def save_selectors(self):
        """Save the selectors to a JSON file"""
        with open('selectors.json', 'w') as f:
            json.dump(self.selectors, f, indent=4)
        print(f"\nSelectors saved to selectors.json")
        
        # Generate a Python code snippet with updated selectors
        self.generate_code_snippet()
    
    def generate_code_snippet(self):
        """Generate a Python code snippet with the updated selectors"""
        code = "# Updated selectors for sprouting_scraper.py\n\n"
        
        # Login selectors
        if 'login_page' in self.selectors:
            code += "# Login page selectors\n"
            for name, selector in self.selectors['login_page'].items():
                code += f"# {name} = '{selector}'\n"
            code += "\n"
        
        # Category page selectors
        if 'category_page' in self.selectors:
            code += "# Category page selectors\n"
            for name, selector in self.selectors['category_page'].items():
                code += f"# {name} = '{selector}'\n"
            code += "\n"
        
        # Product page selectors
        if 'product_page' in self.selectors:
            code += "# Product page selectors\n"
            for name, selector in self.selectors['product_page'].items():
                code += f"# {name} = '{selector}'\n"
        
        with open('selector_snippets.py', 'w') as f:
            f.write(code)
        print(f"Code snippets saved to selector_snippets.py")

async def main():
    parser = argparse.ArgumentParser(description='Sprouting.com Selector Helper')
    parser.add_argument('url', help='URL to examine (e.g., https://sprouting.com/product-category/seeds/all-seeds/)')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    
    args = parser.parse_args()
    
    helper = SelectorHelper(headless=args.headless)
    await helper.run(args.url)

if __name__ == "__main__":
    asyncio.run(main()) 