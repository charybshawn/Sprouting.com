#!/usr/bin/env python3
import os
import csv
import time
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

base_shop_url = "https://sprouting.com/shop/" 

def scrape_product_list(page, max_pages=3):
    """
    Scrapes product titles, URLs, microgreen status, and stock status
    from the product list pages using Playwright only.

    Args:
        page: The Playwright page object.
        max_pages: The maximum number of pages to scrape (for testing).

    Returns:
        A list of dictionaries, where each dictionary contains
        'title', 'url', 'is_microgreen', and 'is_in_stock' of a product.
    """
    products = []
    current_page_num = 1
    base_url_for_products = "https://sprouting.com" 

    if base_shop_url not in page.url:
        print(f"Navigating to initial shop page: {base_shop_url}")
        page.goto(base_shop_url, timeout=60000)
    
    print(f"Waiting for shop page content to load at {page.url}...")
    try:
        page.wait_for_selector('ul.products li.product', timeout=60000) 
        print("Product list detected.")
    except PlaywrightTimeoutError:
        print(f"Timeout waiting for product list on {page.url}. Trying to proceed anyway after domcontentloaded.")
        page.wait_for_load_state('domcontentloaded', timeout=60000) 

    while current_page_num <= max_pages:
        try:
            print(f"Scraping page: {page.url}")

            product_item_locators = page.locator('li.product')
            count = product_item_locators.count()
            if count == 0:
                print(f"No products found on page: {page.url}")
                page.wait_for_timeout(5000) 
                count = product_item_locators.count()
                if count == 0:
                    print(f"Still no products found on page: {page.url} after extra wait. Breaking.")
                    break

            for i in range(count):
                item_locator = product_item_locators.nth(i)
                
                item_classes = item_locator.get_attribute('class')
                is_microgreen = False
                is_in_stock = True 

                if item_classes:
                    if "product_cat-microgreen-seeds" in item_classes:
                        is_microgreen = True
                    if "outofstock" in item_classes:
                        is_in_stock = False

                link_locator = item_locator.locator('a.woocommerce-LoopProduct-link').first
                title_tag = link_locator.locator('h2.woocommerce-loop-product__title').first
                
                title = ""
                if title_tag.count() > 0:
                    title = title_tag.text_content().strip()
                
                product_url = link_locator.get_attribute('href')

                if title and product_url:
                    if not product_url.startswith('http'):
                        product_url = urljoin(base_url_for_products, product_url) 
                    
                    product_data = {
                        'title': title, 
                        'url': product_url,
                        'is_microgreen': is_microgreen,
                        'is_in_stock': is_in_stock
                    }
                    products.append(product_data)
                    print(f"Found product: {title} - URL: {product_url} - Microgreen: {is_microgreen} - In Stock: {is_in_stock}")
                else:
                    item_html_for_log = item_locator.inner_html(timeout=5000) if item_locator.count() > 0 else "Unknown item"
                    print(f"Could not find full title/URL for a product on {page.url}. Item HTML (approx): {item_html_for_log[:200]}...")

            next_page_locator = page.locator('nav.woocommerce-pagination a.next.page-numbers').first
            
            if next_page_locator.count() > 0:
                next_page_url_path = next_page_locator.get_attribute('href')
                if next_page_url_path:
                    next_page_url = urljoin(base_url_for_products, next_page_url_path)

                    if current_page_num < max_pages : 
                        print(f"Navigating to next page: {next_page_url}")
                        page.goto(next_page_url, timeout=60000)
                        time.sleep(3) 
                        current_page_num += 1
                    else:
                        print("Max pages reached. Ending scrape.")
                        break
                else:
                    print("Next page link found, but no href attribute. Ending scrape.")
                    break
            else:
                print("No next page link found or max pages reached. Ending scrape.")
                break
        except PlaywrightTimeoutError:
            print(f"Timeout error on page {page.url}. Skipping page.")
            break
        except Exception as e:
            print(f"An error occurred on page {page.url}: {e}")
            break
    
    return products

def save_products_to_csv(products, filename="product_list.csv"):
    """
    Saves a list of product data to a CSV file.

    Args:
        products: A list of dictionaries, where each dictionary
                  contains product information.
        filename: The name of the CSV file to save.
    """
    if not products:
        print("No products to save.")
        return

    output_filename = os.path.join(os.getcwd(), filename)

    keys = products[0].keys()
    with open(output_filename, 'w', newline='', encoding='utf-8') as output_file:
        dict_writer = csv.DictWriter(output_file, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(products)
    print(f"Products saved to {output_filename}")

def main_sync():
    load_dotenv() 

    username = os.environ.get('SPROUTING_USERNAME')
    password = os.environ.get('SPROUTING_PASSWORD')

    if not username or not password:
        print("SPROUTING_USERNAME and SPROUTING_PASSWORD environment variables must be set or present in .env")
        print("Attempting to scrape without login (public data only).")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False) 
        context = browser.new_context()
        page = context.new_page()

        error_page_counter = 0
        def save_error_page_content(page_content, base_filename="error_page"):
            nonlocal error_page_counter
            error_page_counter += 1
            filename = os.path.join(os.getcwd(), f"{base_filename}_{error_page_counter}.html")
            with open(filename, "w", encoding="utf-8") as f:
                f.write(page_content)
            print(f"Saved page content to {filename} for review.")

        try:
            login_successful = False
            if username and password: 
                print(f"Navigating to login page: https://sprouting.com/my-account/")
                page.goto("https://sprouting.com/my-account/", timeout=60000, wait_until="domcontentloaded")
                print("Login page loaded. Entering credentials.")
                page.fill("input[name='username']", username, timeout=30000)
                page.fill("input[name='password']", password, timeout=30000)
                print("Credentials entered. Clicking login button.")
                
                page.click("button[name='login']", timeout=30000)

                try:
                    print("Waiting for redirect to shop page after login...")
                    page.wait_for_url("https://sprouting.com/shop/**", timeout=30000) 
                    print(f"Successfully redirected to: {page.url}")
                    
                    current_page_content_shop = page.content()
                    body_classes_shop = page.locator('body').get_attribute('class')
                    logout_link_visible_shop = page.locator('a[href*="logout"]').count() > 0 or \
                                             page.locator('a:has-text("Logout")').count() > 0 or \
                                             page.locator('a:has-text("Log out")').count() > 0

                    if body_classes_shop and 'logged-in' in body_classes_shop:
                        login_successful = True
                        print(f"Login successful! Body class 'logged-in' found on {page.url}. User type: {'wholesale_customer' if 'wholesale_customer' in body_classes_shop else 'unknown'}")
                    elif logout_link_visible_shop:
                        login_successful = True
                        print(f"Login successful! Logout link found on {page.url}.")
                    else:
                        print(f"Redirected to {page.url}, but could not confirm logged-in status (no 'logged-in' class or logout link).")
                        save_error_page_content(current_page_content_shop, "error_page_shop_login_check")

                except PlaywrightTimeoutError:
                    print(f"Timeout waiting for redirect to shop page. Current URL: {page.url}")
                    current_page_content_account = page.content()
                    error_message_selectors = [
                        "ul.woocommerce-error li", 
                        ".woocommerce-notices-wrapper .woocommerce-error",
                        ".woocommerce-message"
                    ]
                    login_error_found = False
                    for selector in error_message_selectors:
                        error_elements = page.locator(selector)
                        if error_elements.count() > 0:
                            for i in range(error_elements.count()):
                                error_text = error_elements.nth(i).text_content().strip()
                                print(f"Login Error Found on {page.url}: {error_text}")
                                if "Unknown email address" in error_text or "The password you entered" in error_text:
                                    login_error_found = True
                                    break
                            if login_error_found: break
                    
                    if login_error_found:
                        print("Login failed on /my-account/ page due to incorrect credentials or unknown email.")
                    else:
                        print("Login failed. Did not redirect to shop page, and no specific error messages found on current page.")
                    save_error_page_content(current_page_content_account, "error_page_login_redirect_fail")
            else:
                print("No username/password provided, skipping login.")

            if not login_successful and username and password:
                 print("Halting script due to login failure or inability to confirm login.")
                 # return 

            print(f"Proceeding to scrape. Current page: {page.url}")
            if base_shop_url not in page.url or not login_successful:
                print(f"Navigating to shop page: {base_shop_url}")
                page.goto(base_shop_url, timeout=60000, wait_until="domcontentloaded")
            else:
                print("Already on shop page after successful login. Ensuring content is loaded.")
                page.wait_for_load_state('domcontentloaded', timeout=60000)
            
            scraped_products = scrape_product_list(page, max_pages=2) 

            if scraped_products:
                save_products_to_csv(scraped_products, "sprouting_products.csv")
            else:
                print("No products were scraped.")

        except PlaywrightTimeoutError as e:
            print(f"A Playwright timeout occurred: {e}")
            save_error_page_content(page.content(), "error_page_playwright_timeout")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            try:
                save_error_page_content(page.content(), "error_page_unexpected")
            except Exception as e_save:
                print(f"Could not save error page during unexpected error: {e_save}")
        finally:
            print("Closing browser.")
            browser.close()

if __name__ == "__main__":
    main_sync() 