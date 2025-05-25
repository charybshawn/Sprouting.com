#!/usr/bin/env python3
import os
import re
import json
import argparse
import requests
from bs4 import BeautifulSoup

def test_login(username, password):
    """Test login to sprouting.com using direct HTTP requests"""
    print(f"Testing login with username: {username}")
    
    # Create a session to maintain cookies
    session = requests.Session()
    
    # Set a user agent to appear as a regular browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://sprouting.com/',
        'Origin': 'https://sprouting.com',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Pragma': 'no-cache',
        'Cache-Control': 'no-cache',
    }
    
    session.headers.update(headers)
    
    try:
        # Step 1: Get the login page to extract any required tokens
        print("Getting login page...")
        response = session.get('https://sprouting.com/my-account/')
        
        if response.status_code != 200:
            print(f"Failed to get login page: {response.status_code}")
            return False
        
        # Save the login page HTML for debugging
        with open('requests_login_page.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        print("Login page saved to requests_login_page.html")
        
        # Parse the page to extract any tokens or hidden fields
        soup = BeautifulSoup(response.text, 'html.parser')
        login_form = soup.select_one('form.login')
        
        if not login_form:
            print("Login form not found on page")
            return False
        
        # Extract nonce if present
        nonce = None
        nonce_field = login_form.select_one('input[name="woocommerce-login-nonce"]')
        if nonce_field:
            nonce = nonce_field.get('value')
            print(f"Found login nonce: {nonce}")
        
        # Find all hidden fields
        hidden_fields = {}
        for hidden_field in login_form.select('input[type="hidden"]'):
            name = hidden_field.get('name')
            value = hidden_field.get('value')
            if name and value:
                hidden_fields[name] = value
                print(f"Found hidden field: {name}={value}")
        
        # Step 2: Prepare login data
        login_data = {
            'username': username,
            'password': password,
            'rememberme': 'forever',
            'login': 'Log in'
        }
        
        # Add any hidden fields
        login_data.update(hidden_fields)
        
        # Step 3: Get the form action URL
        form_action = login_form.get('action')
        if not form_action:
            form_action = 'https://sprouting.com/my-account/'
        
        print(f"Form action URL: {form_action}")
        
        # Add additional headers for the POST request
        post_headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': 'https://sprouting.com/my-account/',
        }
        session.headers.update(post_headers)
        
        # Step 4: Submit the login form
        print("Submitting login form...")
        print(f"Login data: {json.dumps(login_data, indent=2)}")
        
        login_response = session.post(form_action, data=login_data, allow_redirects=True)
        
        # Save the response HTML for debugging
        with open('requests_after_login.html', 'w', encoding='utf-8') as f:
            f.write(login_response.text)
        print(f"Response status code: {login_response.status_code}")
        print(f"Response URL: {login_response.url}")
        print("Response saved to requests_after_login.html")
        
        # Step 5: Check if login was successful
        login_soup = BeautifulSoup(login_response.text, 'html.parser')
        
        # Check for error messages
        error_message = login_soup.select_one('.woocommerce-error')
        if error_message:
            error_text = error_message.get_text(strip=True)
            print(f"Error message found: {error_text}")
            return False
        
        # Check if redirected to shop page (common success pattern)
        if 'shop' in login_response.url:
            print(f"Redirected to shop page: {login_response.url}")
            print("This indicates successful login!")
            return True
        
        # Check for success indicators
        success_indicators = [
            '.woocommerce-MyAccount-navigation',
            '.woocommerce-MyAccount-navigation-link--customer-logout',
            'h1.entry-title:contains("My account")',
        ]
        
        for indicator in success_indicators:
            if ':contains(' in indicator:
                # Handle text contains selector
                selector, text = indicator.split(':contains(')
                text = text.strip(')"')
                elements = login_soup.select(selector)
                for element in elements:
                    if text in element.get_text():
                        print(f"Found success indicator: {indicator}")
                        return True
            else:
                element = login_soup.select_one(indicator)
                if element:
                    print(f"Found success indicator: {indicator}")
                    return True
        
        # If we get here, login failed
        print("No success indicators found, login failed")
        return False
        
    except Exception as e:
        print(f"Error during login: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Test login to sprouting.com using requests')
    parser.add_argument('--username', help='Username or email for login')
    parser.add_argument('--password', help='Password for login')
    
    args = parser.parse_args()
    
    # Get credentials
    username = args.username or os.environ.get('SPROUTING_USERNAME') or input("Enter your sprouting.com email: ")
    password = args.password or os.environ.get('SPROUTING_PASSWORD') or input("Enter your sprouting.com password: ")
    
    if not username or not password:
        print("Error: Username and password are required")
        return
    
    # Run test
    success = test_login(username, password)
    
    if success:
        print("\n✅ Login test completed successfully!")
    else:
        print("\n❌ Login test failed!")
        
        # Try to parse error from the response HTML
        try:
            with open('requests_after_login.html', 'r', encoding='utf-8') as f:
                content = f.read()
                soup = BeautifulSoup(content, 'html.parser')
                error = soup.select_one('.woocommerce-error')
                if error:
                    print(f"Error message: {error.get_text(strip=True)}")
                    
                # Look for specific error patterns
                if "Incorrect username or password" in content:
                    print("The provided credentials are incorrect.")
                elif "Please enter a valid email address" in content:
                    print("The provided email format is invalid.")
                elif "too many failed login attempts" in content.lower():
                    print("Your account may be temporarily locked due to too many failed login attempts.")
                elif "captcha" in content.lower():
                    print("The site appears to be using CAPTCHA or other anti-bot measures.")
        except Exception as e:
            print(f"Error parsing response HTML: {e}")

if __name__ == "__main__":
    main() 