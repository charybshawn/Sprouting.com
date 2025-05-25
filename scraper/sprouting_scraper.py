#!/usr/bin/env python3
import csv
import time
import random
import asyncio
import os
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.async_api import async_playwright

class SproutingScraper:
    def __init__(self, username=None, password=None, headless=True):
        self.base_url = "https://sprouting.com"
        self.username = username
        self.password = password
        self.headless = headless
        # self.products = [] # Removed
        self.browser = None
        self.context = None
        self.page = None
        
    async def setup(self):
        """Initialize the browser and context"""
        print("Initializing Playwright and browser...")
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=self.headless,
            args=['--disable-dev-shm-usage', '--no-sandbox']
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080}, 
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
            ignore_https_errors=True,
        )
        self.page = await self.context.new_page()
        self.page.set_default_navigation_timeout(90000) 
        self.page.set_default_timeout(60000) 
        
        self.page.on("console", lambda msg: print(f"BROWSER CONSOLE: {msg.text}"))
        self.page.on("pageerror", lambda err: print(f"BROWSER ERROR: {err}"))
        
        print("Setting up resource blocking (minimal)...")
        # await self.page.route("**/*.{png,jpg,jpeg,gif,svg,webp}", lambda route: route.abort()) # Temporarily disabled
        print("Browser setup complete.")
        
    def http_login(self):
        """Login using direct HTTP requests and return the cookies"""
        if not self.username or not self.password:
            print("HTTP LOGIN: No login credentials provided, skipping.")
            return None
            
        print("HTTP LOGIN: Attempting...")
        
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': f'{self.base_url}/my-account/', 
            'Origin': self.base_url,
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
        }
        session.headers.update(headers)
        
        try:
            print("HTTP LOGIN: Getting login page to extract tokens...")
            login_page_url = f'{self.base_url}/my-account/'
            response = session.get(login_page_url, timeout=30) 
            
            if response.status_code != 200:
                print(f"HTTP LOGIN: Failed to get login page. Status: {response.status_code}")
                return None
            
            # with open('http_login_page.html', 'w', encoding='utf-8') as f:
            #     f.write(response.text) # Optional: for debugging
            
            soup = BeautifulSoup(response.text, 'html.parser')
            login_form = soup.select_one('form.login, form.woocommerce-form-login') # More generic WooCommerce form selector
            
            if not login_form:
                print("HTTP LOGIN: Login form not found on page.")
                return None
            
            hidden_fields = {}
            for hidden_field in login_form.select('input[type="hidden"]'):
                name = hidden_field.get('name')
                value = hidden_field.get('value')
                if name and value:
                    hidden_fields[name] = value
                    print(f"HTTP LOGIN: Found hidden field: {name}={value}")
            
            if "woocommerce-login-nonce" not in hidden_fields:
                 print("HTTP LOGIN: Warning - WooCommerce login nonce not found in hidden fields. Login might fail.")


            login_data = {
                'username': self.username,
                'password': self.password,
                'rememberme': 'forever', # Common WooCommerce field
                'login': 'Log in', # Common button text/name
                **hidden_fields # Add all hidden fields
            }
            
            form_action_url = login_form.get('action')
            if not form_action_url or not form_action_url.startswith('http'):
                form_action_url = login_page_url # Post to the same page if action is relative or missing
            
            print(f"HTTP LOGIN: Form action URL: {form_action_url}")
            print(f"HTTP LOGIN: Submitting login data: { {k:v for k,v in login_data.items() if k != 'password'} }") # Don't log password
            
            post_headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': login_page_url,
            }
            session.headers.update(post_headers) # Update session headers for POST
            
            login_response = session.post(form_action_url, data=login_data, allow_redirects=True, timeout=30)
            
            # with open('http_after_login.html', 'w', encoding='utf-8') as f:
            #     f.write(login_response.text) # Optional: for debugging
            print(f"HTTP LOGIN: Response status code after POST: {login_response.status_code}")
            print(f"HTTP LOGIN: Response URL after POST: {login_response.url}")
            
            login_soup = BeautifulSoup(login_response.text, 'html.parser')
            
            error_message = login_soup.select_one('.woocommerce-error, .woocommerce-notices-wrapper .woocommerce-error') # Check for error messages
            if error_message:
                error_text = error_message.get_text(strip=True)
                print(f"HTTP LOGIN: Error message found on page: {error_text}")
                return None
            
            is_successful = False
            # Primary check: redirection to a page that isn't the login page, especially /shop/ or /my-account/ without a form
            if "/my-account/" in login_response.url:
                if login_soup.select_one('a[href*="logout"], .woocommerce-MyAccount-navigation-link--customer-logout'):
                    is_successful = True
                    print("HTTP LOGIN: Success indicator (logout link on /my-account/) found.")
                elif login_soup.select_one('.woocommerce-MyAccount-content') and "dashboard" in login_soup.select_one('.woocommerce-MyAccount-content').get_text(strip=True).lower():
                    is_successful = True
                    print("HTTP LOGIN: Success indicator (My Account dashboard content on /my-account/) found.")
                elif not login_soup.select_one('form.login, form.woocommerce-form-login'): # No login form visible
                     is_successful = True
                     print("HTTP LOGIN: Success indicator (on My Account page, no login form visible) found.")
            elif "/shop/" in login_response.url: # Redirected to shop is a good sign
                print("HTTP LOGIN: Success indicator (redirected to /shop/) found.")
                # Further check for 'logged-in' body class if possible, as /shop/ can be public
                body_classes = login_soup.body.get('class', []) if login_soup.body else []
                if any("logged-in" in cls for cls in body_classes):
                    print("HTTP LOGIN: Confirmed logged-in state via body class on /shop/ page.")
                    is_successful = True
                else:
                    # If not definitively logged-in via body class, but on /shop/, it's still a positive sign.
                    # The browser verification step will be the ultimate test.
                    print("HTTP LOGIN: Redirected to /shop/. Assuming potential success, will verify in browser.")
                    is_successful = True # Tentatively mark as success to try cookies

            if is_successful:
                print("HTTP LOGIN: Appears successful!")
                cookies = []
                for cookie in session.cookies:
                    cookies.append({
                        'name': cookie.name,
                        'value': cookie.value,
                        'domain': cookie.domain or self.base_url.split('//')[1],
                        'path': cookie.path or '/',
                        'expires': cookie.expires,
                        'httpOnly': cookie.has_nonstandard_attr('HttpOnly') or False,
                        'secure': cookie.secure,
                        'sameSite': 'Lax' # Default to Lax, Playwright needs this. Adjust if specific SameSite is sent by server.
                    })
                
                print(f"HTTP LOGIN: Extracted {len(cookies)} cookies from session.")
                # print(f"HTTP LOGIN: Cookies: {json.dumps(cookies, indent=2)}") # For detailed cookie debugging
                return cookies
            else:
                print("HTTP LOGIN: No definitive success indicators found. Login likely failed.")
                if "Lost your password?" in login_response.text:
                    print("HTTP LOGIN: 'Lost your password?' text found, suggests still on login page.")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"HTTP LOGIN: Request error: {str(e)}")
            return None
        except Exception as e:
            print(f"HTTP LOGIN: An unexpected error occurred: {str(e)}")
            return None
            
    async def login(self):
        """Login to sprouting.com using HTTP and/or browser interaction"""
        if not self.username or not self.password:
            print("BROWSER LOGIN: No credentials provided, skipping login.")
            return False
        
        # print("\n--- Attempting HTTP-based login first ---")
        # http_cookies = self.http_login()
        
        # if http_cookies:
        #     print("BROWSER LOGIN: HTTP login attempt returned cookies. Applying to browser context...")
        #     await self.context.add_cookies(http_cookies)
            
        #     print("BROWSER LOGIN: Navigating to My Account page to verify HTTP login...")
        #     try:
        #         await self.page.goto(f"{self.base_url}/my-account/", wait_until="domcontentloaded", timeout=90000)
        #         print("BROWSER LOGIN: My Account page DOM loaded after applying HTTP cookies.")
                
        #         # Check for logout link or other indicators of being logged in
        #         logout_link_visible = await self.page.is_visible('a[href*="logout"], .woocommerce-MyAccount-navigation-link--customer-logout a', timeout=10000)
        #         my_account_dashboard_visible = await self.page.is_visible('.woocommerce-MyAccount-content', timeout=5000)

        #         if logout_link_visible:
        #             print("BROWSER LOGIN: VERIFIED! Logout link visible after HTTP login and navigation.")
        #             return True
        #         if my_account_dashboard_visible and "dashboard" in (await self.page.text_content('.woocommerce-MyAccount-content')).lower():
        #             print("BROWSER LOGIN: VERIFIED! My Account dashboard content visible after HTTP login and navigation.")
        #             return True
                
        #         page_content = await self.page.content()
        #         if 'log out' in page_content.lower() or 'dashboard' in page_content.lower():
        #             print("BROWSER LOGIN: VERIFIED! 'Log out' or 'Dashboard' text found in page content after HTTP login.")
        #             return True
                
        #         print("BROWSER LOGIN: HTTP login cookies applied, but login state not confirmed on My Account page. Will proceed to browser-based login.")
        #         if not self.headless: await self.page.screenshot(path="debug_http_login_verification_failed.png")

        #     except Exception as e:
        #         print(f"BROWSER LOGIN: Error verifying HTTP login on My Account page: {str(e)}. Proceeding to browser login.")
        #         if not self.headless: await self.page.screenshot(path="debug_http_login_verification_error.png")

        print("\n--- Attempting Browser-based login ONLY ---") # Updated log message
        max_retries = 2 
        for attempt in range(1, max_retries + 1):
            print(f"BROWSER LOGIN: Attempt {attempt}/{max_retries}...")
            try:
                print("BROWSER LOGIN: Navigating to My Account page for form login...")
                await self.page.goto(f"{self.base_url}/my-account/", wait_until="domcontentloaded", timeout=90000)
                print("BROWSER LOGIN: My Account page DOM loaded.")
                
                login_form_selector = 'form.login, form.woocommerce-form-login'
                try:
                    await self.page.wait_for_selector(login_form_selector, state='visible', timeout=30000)
                    print(f"BROWSER LOGIN: Login form ('{login_form_selector}') is visible.")
                except Exception as e:
                    print(f"BROWSER LOGIN: Error: Login form ('{login_form_selector}') not visible after 30s. {str(e)}")
                    if not self.headless: await self.page.screenshot(path=f"error_login_form_not_visible_attempt_{attempt}.png")
                    # Check if already logged in (e.g. if HTTP login partially worked or session persisted)
                    if await self.page.is_visible('a[href*="logout"]', timeout=1000): # Quick check
                         print("BROWSER LOGIN: Logout link found while trying to find login form. Assuming already logged in.")
                         return True
                    continue # Try next attempt if form not found and not logged in
                    
                print(f"BROWSER LOGIN: Filling username: '{self.username}'")
                await self.page.fill('input[name="username"]', self.username, timeout=20000)
                
                print(f"BROWSER LOGIN: Filling password.")
                await self.page.fill('input[name="password"]', self.password, timeout=20000)
                
                print("BROWSER LOGIN: Credentials filled.")
                
                # Click the login button
                # Common selectors for WooCommerce login button:
                # button[name="login"], button.woocommerce-form-login__submit, input[name="login"]
                login_button_selectors = [
                    'button[name="login"]', 
                    'button.woocommerce-form-login__submit', 
                    'button[type="submit"].button', # General submit button
                    'input[value="Log in"]' # Input based submit
                ]
                
                login_button_clicked = False
                for btn_selector in login_button_selectors:
                    if await self.page.is_visible(btn_selector):
                        print(f"BROWSER LOGIN: Clicking login button with selector: {btn_selector}")
                        await self.page.click(btn_selector, timeout=30000, force=True)
                        login_button_clicked = True
                        break
                
                if not login_button_clicked:
                    print("BROWSER LOGIN: Error: Could not find or click any known login button.")
                    if not self.headless: await self.page.screenshot(path=f"error_login_button_not_found_attempt_{attempt}.png")
                    continue

                print("BROWSER LOGIN: Login form submitted. Waiting for navigation or page update...")
                
                # Wait for navigation to complete OR for login form to disappear OR logout link to appear
                await self.page.wait_for_function("""
                    () => {
                        const loginForm = document.querySelector('form.login, form.woocommerce-form-login');
                        const logoutLink = document.querySelector('a[href*="logout"], .woocommerce-MyAccount-navigation-link--customer-logout a');
                        return !loginForm || logoutLink;
                    }
                """, timeout=60000)
                print("BROWSER LOGIN: Page updated after login submission (login form gone or logout link appeared).")

                current_url = self.page.url
                print(f"BROWSER LOGIN: Current URL after login attempt: {current_url}")
                
                # Robust verification after browser login
                logout_link_visible_browser = await self.page.is_visible('a[href*="logout"], .woocommerce-MyAccount-navigation-link--customer-logout a', timeout=10000)
                my_account_dashboard_visible_browser = await self.page.is_visible('.woocommerce-MyAccount-content', timeout=5000)

                if logout_link_visible_browser:
                    print("BROWSER LOGIN: SUCCESS! Logout link visible after browser login.")
                    return True
                if my_account_dashboard_visible_browser and "dashboard" in (await self.page.text_content('.woocommerce-MyAccount-content')).lower():
                    print("BROWSER LOGIN: SUCCESS! My Account dashboard content visible after browser login.")
                    return True
                
                # Fallback check on URL and content if primary selectors fail
                if ("/my-account/" in current_url and not await self.page.is_visible(login_form_selector, timeout=2000)) or "/shop/" in current_url :
                    page_content_after_login = await self.page.content()
                    if 'log out' in page_content_after_login.lower() or 'dashboard' in page_content_after_login.lower():
                        print("BROWSER LOGIN: SUCCESS! (Fallback Check) URL indicates success and critical keywords found.")
                        return True
                    else:
                        print(f"BROWSER LOGIN: URL ({current_url}) seems okay, but 'log out' or 'dashboard' keywords missing from content.")
                        if not self.headless: await self.page.screenshot(path=f"error_login_keywords_missing_attempt_{attempt}.png")
                else:
                    print(f"BROWSER LOGIN: Login attempt {attempt} did not result in expected URL or visible elements.")
                    if await self.page.is_visible('.woocommerce-error', timeout=2000):
                        error_msg = await self.page.text_content('.woocommerce-error')
                        print(f"BROWSER LOGIN: Error message on page: {error_msg.strip()}")
                    if not self.headless: await self.page.screenshot(path=f"error_login_failed_attempt_{attempt}.png")

            except Exception as e:
                print(f"BROWSER LOGIN: Error during attempt {attempt}: {str(e)}")
                if not self.headless: await self.page.screenshot(path=f"error_login_exception_attempt_{attempt}.png")
            
            if attempt < max_retries:
                print(f"BROWSER LOGIN: Retrying in 7 seconds...")
                await asyncio.sleep(7)
        
        print(f"BROWSER LOGIN: All {max_retries} browser-based login attempts failed.")
        return False
            
    async def scrape_product_links(self, category_url):
        """Scrape product links from a category page"""
        product_links = []
        max_retries = 3
        
        for attempt in range(1, max_retries + 1):
            print(f"Loading category page (attempt {attempt}/{max_retries}): {category_url}")
            try:
                await self.page.goto(category_url, wait_until="domcontentloaded", timeout=90000)
                print("Category page DOM loaded.")

                # Wait for product list to appear or for a 'no products' message
                try:
                    await self.page.wait_for_selector('ul.products li.product, .woocommerce-info.woocommerce-no-products-found', timeout=60000)
                    print("Product list or 'no products' info found.")
                except Exception as e:
                    print(f"Timeout waiting for product list or 'no products' message: {e}")
                    if attempt < max_retries:
                        await asyncio.sleep(random.uniform(5,10))
                        continue
                    else:
                        return [] # Failed to load product list area

                # Check if products are actually found
                if await self.page.query_selector('.woocommerce-info.woocommerce-no-products-found'):
                    print("No products found on this category page.")
                    return []

                # Wait for JavaScript to potentially load/modify product elements
                # Wait until the number of products is stable for a few seconds
                print("Waiting for product count to stabilize...")
                await self.page.wait_for_function("""
                    () => {
                        const initialCount = document.querySelectorAll('ul.products li.product').length;
                        return new Promise(resolve => setTimeout(() => {
                            const currentCount = document.querySelectorAll('ul.products li.product').length;
                            resolve(initialCount > 0 && initialCount === currentCount);
                        }, 3000)); // Check stability after 3 seconds
                    }
                """, timeout=60000)
                print("Product count stabilized.")

                # Scroll to load any lazy-loaded products
                print("Scrolling page to ensure all products are loaded...")
                await self.page.evaluate('''async () => {
                    for (let i = 0; i < document.body.scrollHeight; i += 100) {
                        window.scrollTo(0, i);
                        await new Promise(resolve => setTimeout(resolve, 50));
                    }
                    window.scrollTo(0, document.body.scrollHeight);
                    await new Promise(resolve => setTimeout(resolve, 1000)); // final wait
                }''')
                print("Scrolling complete.")
                
                links = await self.page.evaluate('''() => {
                    const products = document.querySelectorAll('ul.products li.product a.woocommerce-LoopProduct-link');
                    return Array.from(products).map(a => a.href);
                }''')
                
                if not links: # Fallback to more comprehensive extraction if needed
                    print("Primary link extraction failed, trying fallback selectors...")
                    links = await self.extract_product_links_from_page()

                if links:
                    product_links.extend(links)
                    print(f"Found {len(links)} products on this page")
                    break  # Success
                else:
                    print("No product links found on this page after all attempts.")
                    if attempt < max_retries:
                        print(f"Retrying link extraction ({attempt+1}/{max_retries})...")
                        await asyncio.sleep(random.uniform(5, 10))
                    else:
                         print("Failed to extract product links after max retries.")
                         return [] # Return empty if no links found after retries
            
            except Exception as e:
                print(f"Error scraping category {category_url} (attempt {attempt}/{max_retries}): {str(e)}")
                if not self.headless:
                    await self.page.screenshot(path=f"error_category_page_{attempt}.png")
                    print(f"Screenshot saved to error_category_page_{attempt}.png")
                if attempt < max_retries:
                    retry_delay = random.uniform(8, 15)
                    print(f"Retrying in {retry_delay:.2f} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    print(f"Failed to scrape category {category_url} after {max_retries} attempts")
        
        print(f"Total product links found for {category_url}: {len(product_links)}")
        return list(set(product_links)) # Return unique links
    
    async def extract_product_links_from_page(self):
        """Extract product links from the current page"""
        links = []
        
        # Try different selectors to find product links
        selectors = [
            'li.product a.woocommerce-LoopProduct-link',
            'li.product a.woocommerce-loop-product__link',
            'li.product h2 a',
            'li.product .woocommerce-loop-product__title a',
            '.products li a.product-link',
            '.products .product a:first-child'
        ]
        
        for selector in selectors:
            product_elements = await self.page.query_selector_all(selector)
            if product_elements and len(product_elements) > 0:
                print(f"Found {len(product_elements)} products using selector: {selector}")
                
                for element in product_elements:
                    href = await element.get_attribute('href')
                    if href:
                        # Ensure it's a full URL
                        if not href.startswith('http'):
                            href = urljoin(self.base_url, href)
                        
                        # Only add if it's a product URL
                        if '/product/' in href:
                            links.append(href)
                
                # If we found links, stop trying other selectors
                if links:
                    break
        
        # If we still have no links, try a more aggressive approach
        if not links:
            print("No product links found with primary selectors, trying alternative approach...")
            all_links = await self.page.query_selector_all('a[href*="/product/"]')
            for link in all_links:
                href = await link.get_attribute('href')
                if href and '/product/' in href:
                    links.append(href)
        
        return links
        
    async def scrape_product_details(self, product_url):
        """Scrape details from a product page"""
        max_retries = 3
        
        for attempt in range(1, max_retries + 1):
            print(f"Loading product page (attempt {attempt}/{max_retries}): {product_url}")
            try:
                await self.page.goto(product_url, wait_until="domcontentloaded", timeout=90000) # Changed from networkidle
                print("Product page DOM loaded.")

                # Verify login state again on product page if expecting personalized prices
                if self.username and self.password:
                    is_logged_in_on_product_page = False
                    try:
                        logout_link = await self.page.query_selector('a[href*="logout"]', timeout=5000)
                        if logout_link:
                             is_logged_in_on_product_page = True
                        else: # Check content if selector fails
                            page_content_product = await self.page.content()
                            if 'log out' in page_content_product.lower() or 'my account' in page_content_product.lower():
                                is_logged_in_on_product_page = True
                        
                        if is_logged_in_on_product_page:
                            print("Confirmed logged-in state on product page.")
                        else:
                            print("WARNING: Not logged in on product page, prices might be default.")
                    except Exception as e_login_check:
                        print(f"Could not confirm login state on product page: {e_login_check}")

                product_name_selector = 'h1.product_title.entry-title'
                price_container_selector = 'p.price'
                
                try:
                    print(f"Waiting for product title: {product_name_selector}")
                    await self.page.wait_for_selector(product_name_selector, state="visible", timeout=90000) # Increased timeout
                    print("Product title visible.")
                except Exception as e:
                    print(f"Timeout waiting for product title: {e}")
                    if not self.headless: await self.page.screenshot(path=f"error_product_title_{product_url.split('/')[-2]}_{attempt}.png")
                    if attempt < max_retries: continue
                    return None

                product_name = await self.get_text(product_name_selector)
                if not product_name:
                    print(f"Could not extract product name from {product_url} using selector {product_name_selector}")
                    if not self.headless: await self.page.screenshot(path=f"error_product_name_missing_{product_url.split('/')[-2]}_{attempt}.png")
                    if attempt < max_retries: continue
                    return None
                
                print(f"Product name: {product_name}")
                product_description = await self.get_text('div.woocommerce-product-details__short-description')
                print(f"Product description: {product_description[:60]}...")

                product = {
                    'url': product_url,
                    'name': product_name.strip(),
                    'description': product_description.strip() if product_description else "",
                    'prices': {}
                }
                
                try:
                    print(f"Waiting for price container: {price_container_selector}")
                    await self.page.wait_for_selector(price_container_selector, state="visible", timeout=90000) # Increased timeout
                    print("Price container visible.")
                    price_selector_js = f'''
                        () => {{
                            const priceElement = document.querySelector("{price_container_selector} .woocommerce-Price-amount bdi");
                            if (priceElement && priceElement.innerText.trim() !== "") {{
                                return priceElement.innerText.trim();
                            }}
                            const priceElementIns = document.querySelector("{price_container_selector} ins .woocommerce-Price-amount bdi");
                             if (priceElementIns && priceElementIns.innerText.trim() !== "") {{
                                return priceElementIns.innerText.trim();
                            }}
                            return null;
                        }}'''
                    price_text = await self.page.wait_for_function(price_selector_js, timeout=60000) # Increased timeout
                    
                    if price_text:
                        price_value = price_text.replace('$', '').replace(',','').strip()
                        product['prices']['default'] = price_value
                        print(f"Extracted price: ${price_value}")
                    else:
                        print(f"Could not extract price text from {price_container_selector}")
                except Exception as e:
                    print(f"Error extracting price for {product_name}: {str(e)}")
                    if not self.headless: await self.page.screenshot(path=f"error_product_price_{product_url.split('/')[-2]}_{attempt}.png")
                
                try:
                    instructions_selector = '.product-growing-instructions, #tab-description .wc-tab-inner, .woocommerce-Tabs-panel--description'
                    description_tab_selector = 'a[href="#tab-description"]'
                    if await self.page.query_selector(description_tab_selector):
                        tab_content_candidate_selector = instructions_selector.split(',')[1].strip()
                        if not await self.page.is_visible(tab_content_candidate_selector):
                            print("Description tab content not visible, attempting to click tab.")
                            await self.page.click(description_tab_selector)
                            await self.page.wait_for_selector(tab_content_candidate_selector, state="visible", timeout=10000)
                    
                    instructions = await self.get_text(instructions_selector)
                    if instructions:
                        product['growing_instructions'] = instructions.strip()
                        print("Extracted growing instructions.")
                except Exception as e:
                    print(f"Error extracting growing instructions for {product_name}: {str(e)}")
                
                print(f"Successfully scraped product: {product_name}")
                return product
                
            except Exception as e:
                print(f"Error scraping product {product_url} (attempt {attempt}/{max_retries}): {str(e)}")
                if not self.headless:
                     await self.page.screenshot(path=f"error_product_page_{product_url.split('/')[-2]}_{attempt}.png")
                     print(f"Screenshot saved to error_product_page_{product_url.split('/')[-2]}_{attempt}.png")
                if attempt < max_retries:
                    retry_delay = random.uniform(8, 15)
                    print(f"Retrying in {retry_delay:.2f} seconds...")
                    await self.page.reload(wait_until="domcontentloaded", timeout=90000) # Changed from networkidle
                    await asyncio.sleep(retry_delay)
                else:
                    print(f"Failed to scrape product {product_url} after {max_retries} attempts")
        return None
            
    async def get_text_for_radio(self, radio_element):
        """Get the label text for a radio button element"""
        try:
            # Get the id of the radio button
            radio_id = await radio_element.get_attribute('id')
            if radio_id:
                # Find the label with a 'for' attribute matching the id
                label = await self.page.query_selector(f'label[for="{radio_id}"]')
                if label:
                    return await label.text_content()
            
            # Fallback: get the value attribute
            return await radio_element.get_attribute('value')
        except:
            return ""
            
    async def get_text(self, selector):
        """Helper method to safely get text content from an element"""
        try:
            element = await self.page.query_selector(selector)
            if element:
                return await element.text_content()
        except:
            pass
        return ""
            
    async def scrape_all_categories(self):
        """Scrape products from all categories"""
        # Updated category URLs based on the actual website structure
        category_urls = [
            urljoin(self.base_url, "/product-category/seeds/all-seeds/")
        ]
        
        all_products = []
        
        for category_url in category_urls:
            print(f"Scraping category: {category_url}")
            product_links = await self.scrape_product_links(category_url)
            
            if not product_links:
                print(f"No product links found for category: {category_url}")
                continue
                
            # Process a subset of products for testing if there are too many
            max_products = 10  # Start with a smaller number to test
            if len(product_links) > max_products:
                print(f"Found {len(product_links)} products, scraping first {max_products} for testing")
                product_links = product_links[:max_products]
            
            products_scraped = 0
            for product_link in product_links:
                print(f"Scraping product {products_scraped+1}/{len(product_links)}: {product_link}")
                try:
                    product = await self.scrape_product_details(product_link)
                    if product:
                        self.products.append(product)
                        products_scraped += 1
                        print(f"Successfully scraped product: {product.get('name', 'Unknown')}")
                        
                        # Save intermediate results every 5 products
                        if products_scraped % 5 == 0:
                            print(f"Saving intermediate results ({products_scraped} products)...")
                            self.save_to_csv(f"sprouting_products_partial_{products_scraped}.csv")
                    else:
                        print(f"Failed to scrape product: {product_link}")
                except Exception as e:
                    print(f"Error scraping product {product_link}: {str(e)}")
                
                # Be nice to the server with a random delay
                delay = random.uniform(2, 5)
                print(f"Waiting {delay:.2f} seconds before next product...")
                await self.page.wait_for_timeout(delay * 1000)
            
            print(f"Finished category: {category_url}. Scraped {products_scraped} products.")
            
        # Add a summary
        print(f"\nScraping Summary:")
        print(f"Total products scraped: {len(self.products)}")
        
        # Return the products
        return self.products

    def save_to_csv(self, filename="sprouting_products.csv"):
        """Save scraped products to CSV file"""
        if not self.products:
            print("No products to save")
            return
            
        # Get all unique price keys across all products
        price_keys = set()
        for product in self.products:
            for key in product.get('prices', {}).keys():
                price_keys.add(key)
                
        price_keys = sorted(list(price_keys))
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            # Define CSV headers
            fieldnames = ['name', 'url', 'description'] + [f'price_{key}' for key in price_keys] + ['growing_instructions']
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for product in self.products:
                row = {
                    'name': product.get('name', ''),
                    'url': product.get('url', ''),
                    'description': product.get('description', ''),
                    'growing_instructions': product.get('growing_instructions', '')
                }
                
                # Add prices for each quantity
                for key in price_keys:
                    row[f'price_{key}'] = product.get('prices', {}).get(key, '')
                
                writer.writerow(row)
                
            print(f"Saved {len(self.products)} products to {filename}")
            
    async def close(self):
        """Close browser and clean up resources"""
        if self.browser:
            print("Closing browser...")
            await self.browser.close()
            print("Browser closed.")

async def main():
    username = os.environ.get('SPROUTING_USERNAME')
    password = os.environ.get('SPROUTING_PASSWORD')

    if not username:
        username = input("Enter your sprouting.com email (leave blank to skip login): ")
    if not password and username: # Only ask for password if username is provided
        password = input("Enter your sprouting.com password: ")
    
    show_browser_input = input("Show browser window? (y/N, default N): ").lower()
    headless = not show_browser_input.startswith('y')
    
    scraper = SproutingScraper(username=username if username and password else None, 
                               password=password if username and password else None, 
                               headless=headless)
    
    login_successful = False
    try:
        await scraper.setup()
        
        if scraper.username and scraper.password:
            print("\n--- STARTING LOGIN PROCESS ---")
            login_successful = await scraper.login()
            
            if login_successful:
                print("\n✅✅✅ LOGIN SUCCEEDED according to script! ✅✅✅")
                print("Final check: Navigating to My Account to confirm post-login state and take screenshot...")
                try:
                    await scraper.page.goto(f"{scraper.base_url}/my-account/", wait_until="load", timeout=60000)
                    print(f"Current URL after final check: {scraper.page.url}")
                    if not scraper.headless:
                        await scraper.page.screenshot(path="final_login_success_state.png")
                        print("Screenshot 'final_login_success_state.png' taken (if not headless).")
                except Exception as e_final_check:
                    print(f"Error during final screenshot navigation: {str(e_final_check)}")
            else:
                print("\n❌❌❌ LOGIN FAILED according to script. ❌❌❌")
                if scraper.page and not scraper.headless: # Check if page exists before screenshot
                    try:
                        await scraper.page.screenshot(path="final_login_failure_state.png")
                        print("Screenshot 'final_login_failure_state.png' taken (if not headless).")
                    except Exception as e_screenshot_fail:
                        print(f"Could not take failure screenshot: {str(e_screenshot_fail)}")
        else:
            print("No login credentials provided. Skipping login process.")
        
        print("\nScript finished. If login was attempted, check logs and screenshots for details.")
        
    except Exception as e:
        print(f"\n❌ MAIN SCRIPT ERROR: An unexpected error occurred: {str(e)}")
        if scraper.page and not scraper.headless:
            try:
                await scraper.page.screenshot(path="main_script_error.png")
            except Exception as e_screenshot_main_error:
                 print(f"Could not take main error screenshot: {str(e_screenshot_main_error)}")
    finally:
        await scraper.close()
        print("Cleanup complete. Exiting.")
    
if __name__ == "__main__":
    asyncio.run(main()) 