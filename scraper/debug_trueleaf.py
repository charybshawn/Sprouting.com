#!/usr/bin/env python3
"""
Debug script for True Leaf Market website structure
"""
import time
from playwright.sync_api import sync_playwright

def debug_trueleaf_market():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Visible browser for debugging
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()
        
        try:
            print("Navigating to True Leaf Market...")
            # First try the main site to see if it's working
            print("Testing main site first...")
            response = page.goto("https://trueleafmarket.com", timeout=30000, wait_until="domcontentloaded")
            print(f"Main site status: {response.status}")
            print(f"Main site title: {page.title()}")
            
            time.sleep(2)
            
            # Look for collection links on the main page
            print("\nLooking for collection links...")
            collection_links = page.locator('a[href*="/collections/"]').all()
            print(f"Found {len(collection_links)} collection links")
            
            microgreen_links = []
            for link in collection_links[:10]:  # Check first 10 links
                href = link.get_attribute('href')
                text = link.text_content()
                if 'micro' in text.lower() or 'green' in text.lower() or 'sprout' in text.lower():
                    microgreen_links.append((href, text))
                    print(f"  Potential microgreen link: {href} - '{text}'")
            
            # Try different microgreen collection URLs
            collection_urls_to_try = [
                "https://trueleafmarket.com/collections/micro-greens-planting-seed",
                "https://trueleafmarket.com/collections/microgreens",
                "https://trueleafmarket.com/collections/micro-greens",
                "https://trueleafmarket.com/collections/sprouting-seeds",
                "https://trueleafmarket.com/collections/sprouts"
            ]
            
            if microgreen_links:
                # Add discovered links to try
                for href, text in microgreen_links:
                    if href.startswith('/'):
                        full_url = f"https://trueleafmarket.com{href}"
                    else:
                        full_url = href
                    if full_url not in collection_urls_to_try:
                        collection_urls_to_try.append(full_url)
            
            working_url = None
            for test_url in collection_urls_to_try:
                print(f"\nTrying: {test_url}")
                try:
                    response = page.goto(test_url, timeout=10000, wait_until="domcontentloaded")
                    page_text = page.locator('body').text_content()
                    
                    if response.status == 200 and '502' not in page_text:
                        print(f"  SUCCESS! Status: {response.status}")
                        working_url = test_url
                        break
                    else:
                        print(f"  Failed: Status {response.status}, has 502 error: {'502' in page_text}")
                except Exception as e:
                    print(f"  Error: {e}")
            
            # Try the Atom feed URL suggested by user
            print("\nTrying Atom feed URL...")
            atom_url = "https://trueleafmarket.com/collections/micro-greens-planting-seed/atom"
            try:
                response = page.goto(atom_url, timeout=10000, wait_until="domcontentloaded")
                print(f"Atom feed status: {response.status}")
                
                if response.status == 200:
                    page_content = page.content()
                    
                    # Save whatever we got for analysis
                    with open('trueleaf_atom_feed.xml', 'w', encoding='utf-8') as f:
                        f.write(page_content)
                    print("Atom feed content saved as trueleaf_atom_feed.xml")
                    
                    print(f"First 500 chars of Atom feed: {page_content[:500]}")
                    
                    if 'xml' in page_content or 'atom' in page_content or 'feed' in page_content:
                        print("SUCCESS! Atom feed is working")
                        
                        # Extract product URLs from the atom feed
                        import re
                        product_urls = re.findall(r'<link[^>]*href="([^"]*products/[^"]*)"', page_content)
                        print(f"Found {len(product_urls)} product URLs in Atom feed:")
                        for i, url in enumerate(product_urls[:5]):
                            print(f"  {i+1}: {url}")
                        
                        if product_urls:
                            working_url = atom_url
                    elif '502' in page_content:
                        print("Atom feed also returns 502 error")
                    else:
                        print("Atom feed returned HTML instead of XML")
                else:
                    print(f"Atom feed failed with status: {response.status}")
            except Exception as e:
                print(f"Error accessing Atom feed: {e}")
            
            if not working_url:
                print("\nNo working microgreen collection URL found")
                return
                
            # Use the working URL
            print(f"\nUsing working URL: {working_url}")
            response = page.goto(working_url, timeout=30000, wait_until="domcontentloaded")
            
            print(f"Response status: {response.status}")
            print(f"Final URL: {page.url}")
            
            # Wait for page to fully load
            time.sleep(5)
            
            # Take screenshot
            page.screenshot(path="trueleaf_debug.png")
            print("Screenshot saved as trueleaf_debug.png")
            
            # Check page title
            title = page.title()
            print(f"Page title: {title}")
            
            # Test various product selectors
            selectors_to_test = [
                '.product-item',
                '.product',
                '.grid-item',
                '.card',
                '[data-product]',
                '.product-card',
                '.product-tile',
                '.item',
                '.grid-product',
                '.collection-item'
            ]
            
            print("\nTesting product selectors:")
            for selector in selectors_to_test:
                count = page.locator(selector).count()
                print(f"  {selector}: {count} elements")
                
                if count > 0:
                    # Get first element's HTML for analysis
                    first_element = page.locator(selector).first
                    outer_html = first_element.get_attribute('outerHTML')
                    print(f"    First element HTML: {outer_html[:200]}...")
            
            # Check for any grid containers
            grid_selectors = [
                '.grid',
                '.product-grid',
                '.collection-grid',
                '.products',
                '.product-list'
            ]
            
            print("\nTesting grid container selectors:")
            for selector in grid_selectors:
                count = page.locator(selector).count()
                print(f"  {selector}: {count} elements")
            
            # Check if there are any links to products
            product_links = page.locator('a[href*="/products/"]').count()
            print(f"\nFound {product_links} links to /products/")
            
            if product_links > 0:
                # Get first few product links
                for i in range(min(3, product_links)):
                    link = page.locator('a[href*="/products/"]').nth(i)
                    href = link.get_attribute('href')
                    text = link.text_content()
                    print(f"  Product link {i+1}: {href} - '{text}'")
            
            # Check page content for any error messages
            page_text = page.locator('body').text_content()
            if 'no products' in page_text.lower():
                print("\nPage contains 'no products' message")
            if 'empty' in page_text.lower():
                print("Page contains 'empty' message")
            if 'coming soon' in page_text.lower():
                print("Page contains 'coming soon' message")
            
            # Print first 500 characters of page text for analysis
            print(f"\nFirst 500 chars of page text: {page_text[:500]}")
            
            # Check if page is redirecting or has issues
            if not page_text.strip():
                print("WARNING: Page appears to be empty!")
            
            # Check for Shopify-specific elements
            shopify_elements = page.locator('[data-shopify]').count()
            print(f"Shopify elements found: {shopify_elements}")
                
            # Get full page source for examination
            with open('trueleaf_page_source.html', 'w', encoding='utf-8') as f:
                f.write(page.content())
            print("\nPage source saved as trueleaf_page_source.html")
            
        except Exception as e:
            print(f"Error during debugging: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    debug_trueleaf_market()