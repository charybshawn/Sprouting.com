#!/usr/bin/env python3
import os
import time
import argparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

def test_login(username, password, headless=False):
    """Test login to sprouting.com using Selenium"""
    print(f"Testing login with username: {username}")
    
    # Set up Chrome options
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument('--headless')
    options.add_argument('--window-size=1280,800')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    
    # Initialize the driver
    driver = webdriver.Chrome(options=options)
    
    try:
        # Set page load timeout
        driver.set_page_load_timeout(60)
        
        # Navigate to login page
        print("Opening login page...")
        driver.get("https://sprouting.com/my-account/")
        
        # Wait for page to load
        time.sleep(3)
        
        # Take screenshot
        driver.save_screenshot("selenium_login_page.png")
        print("Screenshot saved as selenium_login_page.png")
        
        # Print page title
        print(f"Page title: {driver.title}")
        
        # List all forms
        forms = driver.find_elements(By.TAG_NAME, "form")
        print(f"Found {len(forms)} forms on the page")
        
        # Find username and password fields
        try:
            username_field = driver.find_element(By.ID, "username")
            password_field = driver.find_element(By.ID, "password")
            
            print("Found username and password fields")
            
            # Fill in credentials
            print("Entering credentials...")
            username_field.clear()
            username_field.send_keys(username)
            
            password_field.clear()
            password_field.send_keys(password)
            
            # Check remember me box
            try:
                remember_me = driver.find_element(By.NAME, "rememberme")
                if not remember_me.is_selected():
                    remember_me.click()
            except NoSuchElementException:
                print("Remember me checkbox not found")
            
            # Take screenshot before clicking login
            driver.save_screenshot("selenium_before_login.png")
            print("Screenshot saved as selenium_before_login.png")
            
            # Find login button
            try:
                login_button = driver.find_element(By.NAME, "login")
                print("Found login button by name")
            except NoSuchElementException:
                try:
                    login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                    print("Found login button by submit type")
                except NoSuchElementException:
                    try:
                        login_button = driver.find_element(By.CSS_SELECTOR, "input[type='submit']")
                        print("Found login button by submit input")
                    except NoSuchElementException:
                        print("Login button not found, trying to submit form directly")
                        driver.execute_script("document.querySelector('form').submit()")
                        login_button = None
            
            # Click login button if found
            if login_button:
                print("Clicking login button...")
                login_button.click()
            
            # Wait for login to complete
            print("Waiting for login process...")
            time.sleep(5)
            
            # Take screenshot after login attempt
            driver.save_screenshot("selenium_after_login.png")
            print("Screenshot saved as selenium_after_login.png")
            
            # Check if login was successful
            print(f"Current URL: {driver.current_url}")
            
            # Look for success indicators
            success_indicators = [
                (By.CSS_SELECTOR, ".woocommerce-MyAccount-navigation"),
                (By.CSS_SELECTOR, ".woocommerce-MyAccount-navigation-link--customer-logout"),
                (By.XPATH, "//h1[contains(text(), 'My account')]"),
                (By.XPATH, "//div[contains(text(), 'Hello')]")
            ]
            
            login_success = False
            for locator_type, locator in success_indicators:
                try:
                    driver.find_element(locator_type, locator)
                    login_success = True
                    print(f"Found success indicator: {locator}")
                    break
                except NoSuchElementException:
                    pass
            
            # Check for error messages
            try:
                error_msg = driver.find_element(By.CSS_SELECTOR, ".woocommerce-error")
                print(f"Error message: {error_msg.text}")
            except NoSuchElementException:
                pass
            
            if login_success:
                print("✅ Login successful!")
                return True
            else:
                print("❌ Login failed!")
                
                # Save page source for debugging
                with open("selenium_login_failed.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print("Full page HTML saved to selenium_login_failed.html")
                
                return False
                
        except NoSuchElementException as e:
            print(f"Element not found: {e}")
            driver.save_screenshot("selenium_error.png")
            print("Error screenshot saved as selenium_error.png")
            
            # Save page source for debugging
            with open("selenium_error.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Error page HTML saved to selenium_error.html")
            
            return False
            
    except Exception as e:
        print(f"Error during login test: {e}")
        try:
            driver.save_screenshot("selenium_exception.png")
            print("Exception screenshot saved as selenium_exception.png")
        except:
            pass
        return False
        
    finally:
        # Close the browser
        driver.quit()

def main():
    parser = argparse.ArgumentParser(description='Test login to sprouting.com using Selenium')
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
    success = test_login(username, password, args.headless)
    
    if success:
        print("\n✅ Login test completed successfully!")
    else:
        print("\n❌ Login test failed!")

if __name__ == "__main__":
    main() 