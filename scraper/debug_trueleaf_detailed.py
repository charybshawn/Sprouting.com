#!/usr/bin/env python3
"""
Detailed debug script for True Leaf Market atom page
"""
import time
from playwright.sync_api import sync_playwright

def debug_trueleaf_atom():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Visible browser
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            print("Navigating to True Leaf Market atom URL...")
            url = "https://trueleafmarket.com/collections/micro-greens-planting-seed/atom"
            response = page.goto(url, timeout=30000, wait_until="domcontentloaded")
            
            print(f"Response status: {response.status}")
            print(f"Response headers: {response.headers}")
            
            # Wait for page to load
            time.sleep(5)
            
            page_content = page.content()
            print(f"Page content length: {len(page_content)}")
            
            # Check if it's XML or HTML
            if '<?xml' in page_content or '<feed' in page_content:
                print("✅ This appears to be XML content")
                # Try to find XML entries
                if '<entry>' in page_content:
                    entry_count = page_content.count('<entry>')
                    print(f"Found {entry_count} XML entries")
                else:
                    print("No XML entries found")
            else:
                print("📄 This appears to be HTML content")
                
                # Check page title
                title = page.title()
                print(f"Page title: '{title}'")
                
                # Count all elements on page
                all_elements = page.locator('*').count()
                print(f"Total elements on page: {all_elements}")
                
                # Test various selectors that might contain products
                selectors_to_test = [
                    'div', 'article', 'section', 'li', 'span', 'p', 'h1', 'h2', 'h3', 'h4',
                    '[class*="product"]', '[class*="item"]', '[class*="card"]', '[class*="tile"]',
                    '[class*="grid"]', '[id*="product"]', '[data-product]',
                    'a[href*="/products/"]', 'a[href*="seed"]', 'a[href*="micro"]'
                ]
                
                print(f"\nTesting {len(selectors_to_test)} selectors:")
                found_selectors = []
                for selector in selectors_to_test:
                    try:
                        count = page.locator(selector).count()
                        if count > 0:
                            print(f"  ✅ {selector}: {count} elements")
                            found_selectors.append((selector, count))
                        else:
                            print(f"  ❌ {selector}: 0 elements")
                    except Exception as e:
                        print(f"  ⚠️  {selector}: Error - {e}")
                
                # Show top-level structure
                print(f"\nBody children:")
                body_children = page.locator('body > *').all()
                for i, child in enumerate(body_children[:10]):  # First 10 children
                    tag_name = child.evaluate('el => el.tagName')
                    class_name = child.get_attribute('class') or ''
                    id_name = child.get_attribute('id') or ''
                    print(f"  {i+1}: <{tag_name.lower()}> class='{class_name}' id='{id_name}'")
                
                # Look for text content that mentions seeds or microgreens
                page_text = page.locator('body').text_content()
                microgreen_mentions = page_text.lower().count('microgreen')
                seed_mentions = page_text.lower().count('seed')
                print(f"\nContent analysis:")
                print(f"  'microgreen' mentions: {microgreen_mentions}")
                print(f"  'seed' mentions: {seed_mentions}")
                
                # Check for common e-commerce platforms
                if 'shopify' in page_content.lower():
                    print("  Platform: Shopify detected")
                if 'woocommerce' in page_content.lower():
                    print("  Platform: WooCommerce detected")
                
                # Save page source for manual inspection
                with open('trueleaf_atom_debug.html', 'w', encoding='utf-8') as f:
                    f.write(page_content)
                print(f"\nPage source saved to: trueleaf_atom_debug.html")
                
                # Try to find any product-like links
                product_links = page.locator('a[href*="/products/"]').all()
                if product_links:
                    print(f"\nFound {len(product_links)} product links:")
                    for i, link in enumerate(product_links[:5]):
                        href = link.get_attribute('href')
                        text = link.text_content()[:50]
                        print(f"  {i+1}: {href} - '{text}...'")
                else:
                    print("\nNo product links found")
                    
                    # Try broader link search
                    all_links = page.locator('a[href]').all()
                    print(f"Found {len(all_links)} total links")
                    seed_links = []
                    for link in all_links[:20]:  # Check first 20 links
                        href = link.get_attribute('href')
                        text = link.text_content().lower()
                        if 'seed' in text or 'micro' in text or 'green' in text:
                            seed_links.append((href, text[:50]))
                    
                    if seed_links:
                        print(f"Found {len(seed_links)} seed-related links:")
                        for href, text in seed_links:
                            print(f"  {href} - '{text}...'")
                    else:
                        print("No seed-related links found")
                        
        except Exception as e:
            print(f"Error during debugging: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    debug_trueleaf_atom()