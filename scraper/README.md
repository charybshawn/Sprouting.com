# Sprouting.com Web Scraper

A Python script to extract product and pricing information from sprouting.com (Mumm's Sprouting Seeds), including support for login to access personalized pricing.

## Features

- **Login Support**: Access your account-specific pricing tiers
- **Browser Automation**: Uses Playwright to handle dynamic content and interactions
- **Complete Data Extraction**: Scrapes product names, descriptions, and prices for different quantities (75g, 150g, 1kg, 5kg, 10kg)
- **Data Analysis**: Tools to analyze pricing patterns and generate visualizations
- **CSV Export**: Saves data in CSV format for easy analysis

## Installation

### Quick Setup (Recommended)

Run the included setup script:

```
./setup.sh
```

The script will:
1. Check for Python 3.7+ installation
2. Optionally create a virtual environment
3. Install required Python packages
4. Install Playwright browsers
5. Provide instructions for next steps

### Manual Installation

If you prefer to install manually:

1. Ensure you have Python 3.7+ installed
2. Install required packages:
   ```
   pip install -r requirements.txt
   ```
3. Install Playwright browsers:
   ```
   python -m playwright install
   ```

## Usage

Run the scraper with:

```
python sprouting_scraper.py
```

You will be prompted to:
1. Enter your sprouting.com login credentials (optional)
2. Choose whether to show the browser window during scraping

The script will then:
1. Log in to your account (if credentials provided)
2. Visit sprouting.com product categories
3. Extract product information with your personalized pricing
4. Save the data to `sprouting_products.csv`

### Environment Variables

You can set these environment variables to avoid entering credentials each time:
- `SPROUTING_USERNAME`: Your sprouting.com email
- `SPROUTING_PASSWORD`: Your sprouting.com password

## Analyzing Data

After scraping, run the analysis script:

```
python analyze_products.py
```

## Selector Helper Tool

The project includes a helper tool to assist with finding and updating CSS selectors for the website. This is especially useful when the website structure changes or you need to customize the scraper.

Run the selector helper with:

```
python selector_helper.py URL
```

Where `URL` is the page you want to examine, for example:
- `https://sprouting.com/account/login` (login page)
- `https://sprouting.com/collections/microgreens` (category page)
- `https://sprouting.com/products/some-product` (product page)

The helper will:
1. Open the page in a browser
2. Verify existing selectors and let you update them
3. Provide an interactive tool to test and save new selectors
4. Generate a JSON file and Python code snippets with the updated selectors

Add the `--headless` flag to run without a visible browser window:

```
python selector_helper.py URL --headless
```

## Customization

- Edit the `category_urls` list in the `scrape_all_categories` method to focus on specific product categories
- Modify the CSS selectors in the script to match the current website structure
- Adjust the delay between requests to be respectful of the website's server

## Notes

- This script is for educational purposes only
- Always review the website's robots.txt and terms of service before scraping
- The CSS selectors need to be updated based on actual website inspection 