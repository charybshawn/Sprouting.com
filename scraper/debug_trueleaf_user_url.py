#!/usr/bin/env python3
"""
Debug script to test the specific URL the user mentioned works for them
"""
import time
from playwright.sync_api import sync_playwright

def debug_user_url():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            # Test the exact URL the user said works
            url = "https://trueleafmarket.com/collections/micro-greens-planting-seed"
            print(f"Testing user's working URL: {url}")
            
            response = page.goto(url, timeout=30000, wait_until="domcontentloaded")
            print(f"Response status: {response.status}")
            print(f"Final URL: {page.url}")
            
            time.sleep(3)
            
            # Check page title and basic content
            title = page.title()
            print(f"Page title: '{title}'")
            
            page_text = page.locator('body').text_content()
            print(f"Page text length: {len(page_text)}")
            print(f"Contains 'microgreen': {'microgreen' in page_text.lower()}")
            print(f"Contains 'seed': {'seed' in page_text.lower()}")
            print(f"Contains '502': {'502' in page_text}")
            
            # Check if we're actually on a collection page
            if 'collections' not in page.url:
                print(f"WARNING: URL redirected away from collections page to: {page.url}")
            
            # Look for any product-related content
            product_links = page.locator('a[href*="/products/"]').count()
            print(f"Product links found: {product_links}")
            
            # Test all the selectors we use in the scraper
            selectors = [
                '.product-item',
                '.product-card', 
                '.product',
                '.grid-item',
                '[data-product]',
                '.collection-item',
                '.item',
                'article'
            ]
            
            print("\nTesting scraper selectors:")
            for selector in selectors:
                count = page.locator(selector).count()
                print(f"  {selector}: {count} elements")
                if count > 0:
                    first_elem = page.locator(selector).first
                    try:
                        # Try to get some identifying info about the first element
                        classes = first_elem.get_attribute('class') or ''
                        tag = first_elem.evaluate('el => el.tagName')
                        print(f"    First element: <{tag.lower()}> class='{classes}'")
                    except:
                        pass
            
            # Check for common Shopify structures
            shopify_selectors = [
                '.collection',
                '.product-list',
                '.grid',
                '.products',
                '.collection-grid',
                '.shopify-section'
            ]
            
            print("\nTesting Shopify-specific selectors:")
            for selector in shopify_selectors:
                count = page.locator(selector).count()
                if count > 0:
                    print(f"  {selector}: {count} elements")
            
            # Look for any content that suggests this is the right page
            if product_links > 0:
                print("\n✅ Found product links - this appears to be working!")
                # Show first few product links
                for i in range(min(3, product_links)):
                    link = page.locator('a[href*="/products/"]').nth(i)
                    href = link.get_attribute('href')
                    text = link.text_content()[:50]
                    print(f"  {i+1}: {href} - '{text}...'")
            else:
                print("\n❌ No product links found")
                
                # Check if page has "no products" or similar messages
                no_products_indicators = [
                    'no products',
                    'empty collection',
                    'coming soon',
                    'out of stock',
                    'temporarily unavailable'
                ]
                
                for indicator in no_products_indicators:
                    if indicator in page_text.lower():
                        print(f"  Found indicator: '{indicator}'")
            
            # Save page for inspection
            with open('trueleaf_user_url_debug.html', 'w', encoding='utf-8') as f:
                f.write(page.content())
            print(f"\nPage source saved to: trueleaf_user_url_debug.html")
            
            # Take screenshot
            page.screenshot(path="trueleaf_user_url_debug.png")
            print("Screenshot saved to: trueleaf_user_url_debug.png")
            
        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    debug_user_url()