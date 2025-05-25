#!/usr/bin/env python3
import asyncio
import os
import argparse
import time
from playwright.async_api import async_playwright

async def test_login(username, password, headless=False):
    """Test login functionality for sprouting.com"""
    print(f"Testing login with username: {username}")
    
    async with async_playwright() as playwright:
        # Launch with slower animations for debugging
        browser = await playwright.chromium.launch(
            headless=headless,
            slow_mo=500 if not headless else None  # Add 500ms delay between actions when in visible mode
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        
        # Increase timeout
        context.set_default_timeout(60000)  # 60 seconds
        
        # Enable console logging
        page = await context.new_page()
        page.on("console", lambda msg: print(f"BROWSER CONSOLE: {msg.text}"))
        
        try:
            # Navigate to login page
            print("Opening login page...")
            await page.goto("https://sprouting.com/my-account/", wait_until="domcontentloaded")
            
            # Wait explicitly for the page to be interactive
            await asyncio.sleep(3)
            
            # Save screenshot
            await page.screenshot(path="login_page_test.png")
            print("Screenshot saved as login_page_test.png")
            
            # Print page title to verify we're on the right page
            title = await page.title()
            print(f"Page title: {title}")
            
            # List all forms on the page for debugging
            forms = await page.query_selector_all('form')
            print(f"Found {len(forms)} forms on the page")
            
            for i, form in enumerate(forms):
                form_id = await form.get_attribute('id') or 'no-id'
                form_class = await form.get_attribute('class') or 'no-class'
                print(f"Form {i+1}: id='{form_id}', class='{form_class}'")
            
            # Try to find all possible username/password fields
            username_fields = await page.query_selector_all('input[type="text"], input[type="email"], input#username')
            password_fields = await page.query_selector_all('input[type="password"]')
            
            print(f"Found {len(username_fields)} possible username fields")
            print(f"Found {len(password_fields)} possible password fields")
            
            # Check if login form exists
            login_form = await page.query_selector('form.login, form.woocommerce-form-login')
            if not login_form:
                print("Warning: Login form not found with standard selectors")
                
                # Try to dump the login area HTML for debugging
                login_area = await page.query_selector('.u-column1, .col-1, .login')
                if login_area:
                    html = await login_area.inner_html()
                    print("\nLogin area HTML:")
                    print(html[:500] + "..." if len(html) > 500 else html)
            else:
                print("Login form found successfully")
            
            # Try to fill in credentials using JavaScript for more reliability
            print("Entering credentials using JavaScript...")
            
            # First try the standard method
            username_filled = await page.evaluate(f'''() => {{
                const userField = document.querySelector('input#username');
                if (userField) {{
                    userField.value = "{username}";
                    return true;
                }}
                return false;
            }}''')
            
            password_filled = await page.evaluate(f'''() => {{
                const passField = document.querySelector('input#password');
                if (passField) {{
                    passField.value = "{password}";
                    return true;
                }}
                return false;
            }}''')
            
            print(f"Filled username with JS: {username_filled}")
            print(f"Filled password with JS: {password_filled}")
            
            # If JavaScript filling didn't work, try the regular way
            if not username_filled or not password_filled:
                print("Falling back to regular form filling...")
                
                if len(username_fields) > 0:
                    print(f"Filling first available username field...")
                    await username_fields[0].fill(username)
                    
                if len(password_fields) > 0:
                    print(f"Filling first available password field...")
                    await password_fields[0].fill(password)
            
            # Ensure form fields are filled
            await page.screenshot(path="credentials_filled.png")
            print("Screenshot saved as credentials_filled.png")
            
            # Check remember me box
            remember_me = await page.query_selector('input[name="rememberme"]')
            if remember_me:
                await remember_me.check()
                
            # Find all possible login buttons
            login_buttons = await page.query_selector_all('button[name="login"], input[type="submit"], button[type="submit"]')
            print(f"Found {len(login_buttons)} possible login buttons")
            
            # Take screenshot before clicking login
            await page.screenshot(path="before_login_click.png")
            print("Screenshot saved as before_login_click.png")
            
            # Try clicking the login button using JavaScript
            print("Attempting to submit form via JavaScript...")
            form_submitted = await page.evaluate('''() => {
                const loginForm = document.querySelector('form.login, form.woocommerce-form-login');
                if (loginForm) {
                    loginForm.submit();
                    return true;
                }
                
                // If form wasn't found, try to click the login button
                const loginBtn = document.querySelector('button[name="login"], input[type="submit"], button[type="submit"]');
                if (loginBtn) {
                    loginBtn.click();
                    return true;
                }
                
                return false;
            }''')
            
            print(f"Form submitted via JavaScript: {form_submitted}")
            
            # If JavaScript didn't work, try clicking directly
            if not form_submitted and len(login_buttons) > 0:
                print("Falling back to direct button click...")
                await login_buttons[0].click()
            
            # Wait for navigation
            print("Waiting for page to load after login...")
            try:
                # Wait for either navigation or load state
                await page.wait_for_url("**/my-account/**", timeout=30000)
                print("URL changed, login form submitted")
            except Exception as e:
                print(f"No URL change detected: {str(e)}")
                # If URL didn't change, wait for network idle
                try:
                    await page.wait_for_load_state("networkidle", timeout=30000)
                    print("Page reached network idle state")
                except Exception as e2:
                    print(f"Network idle timeout: {str(e2)}")
                
            # Save screenshot of result
            await page.screenshot(path="after_login_test.png")
            print("Screenshot saved as after_login_test.png")
            
            # Get current URL to help debug
            current_url = page.url
            print(f"Current URL after login attempt: {current_url}")
            
            # Check for success indicators
            account_nav = await page.query_selector('.woocommerce-MyAccount-navigation')
            logout_link = await page.query_selector('a.woocommerce-MyAccount-navigation-link--customer-logout')
            welcome_text = await page.query_selector('text=Hello')
            dashboard_heading = await page.query_selector('h1:text("My account")')
            
            # Check for error messages
            error = await page.query_selector('.woocommerce-error')
            error_text = ""
            if error:
                error_text = await error.text_content()
                print(f"Error message found: {error_text}")
            
            # Determine if login was successful
            if account_nav or logout_link or welcome_text or dashboard_heading:
                print("✅ Login successful!")
                return True
            else:
                print("❌ Login failed!")
                
                # Try to dump the page content for debugging
                try:
                    page_content = await page.content()
                    with open("login_failed_page.html", "w", encoding="utf-8") as f:
                        f.write(page_content)
                    print("Full page HTML saved to login_failed_page.html")
                except Exception as dump_error:
                    print(f"Could not dump page content: {str(dump_error)}")
                    
                return False
                
        except Exception as e:
            print(f"Error during login test: {str(e)}")
            await page.screenshot(path="login_error.png")
            print("Error screenshot saved as login_error.png")
            return False
            
        finally:
            await browser.close()

async def main():
    parser = argparse.ArgumentParser(description='Test login to sprouting.com')
    parser.add_argument('--username', help='Username or email for login')
    parser.add_argument('--password', help='Password for login')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    
    args = parser.parse_args()
    
    # Get credentials
    username = args.username or os.environ.get('SPROUTING_USERNAME') or input("Enter your sprouting.com email: ")
    password = args.password or os.environ.get('SPROUTING_PASSWORD') or input("Enter your sprouting.com password: ")
    
    if not username or not password:
        print("Error: Username and password are required")
        return
    
    # Run test
    success = await test_login(username, password, args.headless)
    
    if success:
        print("\n✅ Login test completed successfully!")
    else:
        print("\n❌ Login test failed!")

if __name__ == "__main__":
    asyncio.run(main()) 