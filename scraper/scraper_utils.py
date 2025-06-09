"""
Shared utilities for all scrapers in the Sprouting.com project.
Centralizes common functionality to reduce code duplication.
"""

import os
import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from logging.handlers import RotatingFileHandler
import time
from functools import wraps
import requests
from urllib.parse import urljoin, urlparse


def setup_logging(scraper_name: str, log_dir: str = "logs") -> logging.Logger:
    """
    Set up logging configuration for a scraper.
    
    Args:
        scraper_name: Name of the scraper (used for log file naming)
        log_dir: Directory to store log files
        
    Returns:
        Configured logger instance
    """
    # Create logs directory if it doesn't exist
    os.makedirs(log_dir, exist_ok=True)
    
    # Create logger
    logger = logging.getLogger(scraper_name)
    logger.setLevel(logging.DEBUG)
    
    # Create formatters
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, f'{scraper_name}.log'),
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


class ScrapingConfig:
    """Configuration class for scraping performance and safety settings."""
    
    def __init__(self, speed_mode: str = "safe"):
        """
        Initialize scraping configuration.
        
        Args:
            speed_mode: "conservative", "safe", "fast", or "aggressive"
        """
        self.speed_mode = speed_mode
        self._configure_for_mode()
    
    def _configure_for_mode(self):
        """Set configuration values based on speed mode."""
        if self.speed_mode == "conservative":
            self.request_delay = 2.0          # 2 seconds between requests
            self.page_timeout = 90000         # 90 seconds
            self.element_timeout = 30000      # 30 seconds
            self.concurrent_requests = 1      # Sequential only
            self.wait_strategy = "load"       # Wait for all resources
            
        elif self.speed_mode == "safe":      # Recommended default
            self.request_delay = 0.5          # 500ms between requests
            self.page_timeout = 30000         # 30 seconds
            self.element_timeout = 15000      # 15 seconds
            self.concurrent_requests = 1      # Sequential only
            self.wait_strategy = "domcontentloaded"
            
        elif self.speed_mode == "fast":
            self.request_delay = 0.2          # 200ms between requests
            self.page_timeout = 15000         # 15 seconds
            self.element_timeout = 8000       # 8 seconds
            self.concurrent_requests = 2      # 2 concurrent requests
            self.wait_strategy = "domcontentloaded"
            
        elif self.speed_mode == "aggressive": # High risk
            self.request_delay = 0.05         # 50ms between requests
            self.page_timeout = 10000         # 10 seconds
            self.element_timeout = 5000       # 5 seconds
            self.concurrent_requests = 3      # 3 concurrent requests
            self.wait_strategy = "domcontentloaded"
        else:
            raise ValueError(f"Unknown speed_mode: {self.speed_mode}")
    
    def get_request_delay(self) -> float:
        """Get delay between requests in seconds."""
        return self.request_delay
    
    def get_page_timeout(self) -> int:
        """Get page load timeout in milliseconds."""
        return self.page_timeout
    
    def get_element_timeout(self) -> int:
        """Get element wait timeout in milliseconds."""
        return self.element_timeout


def retry_on_failure(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    Decorator to retry a function on failure with exponential backoff.
    
    Args:
        max_attempts: Maximum number of attempts
        delay: Initial delay between retries in seconds
        backoff: Multiplier for delay after each retry
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        time.sleep(current_delay)
                        current_delay *= backoff
                    
            raise last_exception
        return wrapper
    return decorator


def parse_weight_from_string(weight_str: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Parse weight information from a string and convert to kilograms.
    
    Args:
        weight_str: String containing weight information
        
    Returns:
        Tuple of (weight_in_kg, original_value, original_unit)
    """
    if not weight_str:
        return None, None, None
    
    # Clean the string
    weight_str = weight_str.lower().strip()
    
    # Define conversion factors to kg
    conversions = {
        'kg': 1.0,
        'kgs': 1.0,
        'kilo': 1.0,
        'kilos': 1.0,
        'killos': 1.0,  # Handle typo variant
        'kilogram': 1.0,
        'kilograms': 1.0,
        'g': 0.001,
        'gr': 0.001,
        'gs': 0.001,  # Add support for "gs" abbreviation
        'gram': 0.001,
        'grams': 0.001,
        'lb': 0.453592,
        'lbs': 0.453592,
        'pound': 0.453592,
        'pounds': 0.453592,
        'oz': 0.0283495,
        'ounce': 0.0283495,
        'ounces': 0.0283495
    }
    
    # Try different patterns - fractions MUST come first, then multiplication patterns
    patterns = [
        r'(\d+)/(\d+)\s*(kg|kgs|kilo|kilos|killos|gs|g|gr|gram|grams|lb|lbs|pound|pounds|oz|ounce|ounces)',  # Fractions (FIRST)
        r'(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(kg|kgs|kilo|kilos|killos|gs|g|gr|gram|grams|lb|lbs|pound|pounds|oz|ounce|ounces)',  # Multiple weights (SECOND)
        r'(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(?:kilogram|kilograms)',  # Multiple kilograms (THIRD)
        r'(\d+(?:\.\d+)?)\s*(kg|kgs|kilo|kilos|killos|gs|g|gr|gram|grams|lb|lbs|pound|pounds|oz|ounce|ounces)',  # Single weight
        r'(\d+(?:\.\d+)?)\s*(?:kilogram|kilograms)'  # Kilogram without abbreviation
    ]
    
    for pattern in patterns:
        match = re.search(pattern, weight_str)
        if match:
            groups = match.groups()
            
            # Check if this is a fraction pattern (3 groups where first two are numbers)
            if (len(groups) == 3 and 
                pattern.startswith(r'(\d+)/(\d+)') and 
                groups[0].isdigit() and groups[1].isdigit()):
                # Handle fractions (e.g., "1/4 pound")
                numerator = float(groups[0])
                denominator = float(groups[1])
                unit = groups[2]
                total_weight = numerator / denominator
                original_value = total_weight  # Fraction result in original units
                
            elif len(groups) == 3:  # Multiple weights (e.g., "5 x 500g")
                quantity = float(groups[0])
                weight = float(groups[1])
                unit = groups[2]
                total_weight = quantity * weight
                original_value = total_weight  # Total in original units
                
            elif len(groups) == 2:  # Single weight
                total_weight = float(groups[0])
                unit = groups[1]
                original_value = total_weight  # Same as total for single weights
            else:
                continue
                
            # Convert to kg
            if unit in conversions:
                weight_kg = total_weight * conversions[unit]
                # Normalize "killos" typo to "kilos"
                normalized_unit = "kilos" if unit == "killos" else unit
                return weight_kg, original_value, normalized_unit
            elif 'kilogram' in str(groups[-1]):
                return total_weight, original_value, 'kg'
    
    return None, None, None


def standardize_size_format(size_str: str) -> str:
    """
    Standardize size/weight format for consistency.
    
    Args:
        size_str: Original size string
        
    Returns:
        Standardized size string
    """
    if not size_str:
        return size_str
    
    # Clean up the string
    size_str = size_str.strip()
    
    # Normalize units to full names for consistency across scrapers
    # Handle "gs" -> "grams"
    size_str = re.sub(r'\bgs\b', 'grams', size_str)
    
    # Handle "g" -> "grams" (but not in the middle of words)
    size_str = re.sub(r'\bg\b', 'grams', size_str)
    
    # Handle "kg" -> "kilograms"
    size_str = re.sub(r'\bkg\b', 'kilograms', size_str)
    
    # Handle "kilo" and "kilos" -> "kilograms"
    size_str = re.sub(r'\bkilos?\b', 'kilograms', size_str)
    
    # Handle "killos" typo -> "kilograms"
    size_str = re.sub(r'\bkillos\b', 'kilograms', size_str)
    
    # Handle "lb" and "lbs" -> "pounds"
    size_str = re.sub(r'\blbs?\b', 'pounds', size_str)
    
    # Handle "oz" -> "ounces"
    size_str = re.sub(r'\boz\b', 'ounces', size_str)
    
    # Ensure space between number and unit
    size_str = re.sub(r'(\d)([a-zA-Z])', r'\1 \2', size_str)
    
    # Remove multiple spaces
    size_str = ' '.join(size_str.split())
    
    return size_str


def extract_price(price_str: str) -> Optional[float]:
    """
    Extract numeric price from a string.
    
    Args:
        price_str: String containing price information
        
    Returns:
        Extracted price as float, or None if not found
    """
    if not price_str:
        return None
    
    # Remove currency symbols and clean
    price_str = re.sub(r'[$£€¥₹]', '', str(price_str))
    price_str = price_str.replace(',', '')
    
    # Extract first number
    match = re.search(r'(\d+(?:\.\d+)?)', price_str)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    
    return None


def calculate_canada_post_shipping(weight_kg: float) -> float:
    """
    Calculate Canada Post Expedited Parcel shipping cost based on weight.
    Based on real invoice data from sprouting.com with economies of scale.
    
    Args:
        weight_kg: Package weight in kilograms
        
    Returns:
        Shipping cost in CAD
    """
    if weight_kg <= 0:
        return 0.0
    
    # Weight tiers based on real invoice data analysis
    # Data points: 2kg->$25.80, 3kg->$26.70, 5kg->$35.09, 10kg->$41.52, 
    # 11kg->$42.87, 13kg->$46.79, 31.8kg->$92.22, 35kg->$93.89, 52kg->$121.62
    
    if weight_kg <= 2:
        # Small orders: $12.90/kg
        return weight_kg * 12.90
    elif weight_kg <= 5:
        # Medium orders: $7.02/kg
        return weight_kg * 7.02
    elif weight_kg <= 15:
        # Large orders: $4.15/kg average
        return weight_kg * 4.15
    elif weight_kg <= 35:
        # Very large orders: $2.90/kg average
        return weight_kg * 2.90
    else:
        # Bulk orders: $2.34/kg
        return weight_kg * 2.34


def calculate_canadian_import_costs(
    base_price: float,
    source_currency: str = "CAD",
    province: str = "BC",
    min_shipping: float = 0.0,
    max_shipping: float = 0.0,
    brokerage_fee: float = 0.0,
    weight_kg: float = None,
    commercial_use: bool = True
) -> Dict[str, float]:
    """
    Calculate Canadian import costs including shipping, duties, taxes, and brokerage.
    
    Args:
        base_price: Product price in source currency
        source_currency: Currency of the base price (CAD, USD)
        province: Canadian province for tax calculation
        min_shipping: Minimum shipping cost in source currency
        max_shipping: Maximum shipping cost in source currency
        brokerage_fee: Brokerage fee in CAD
        weight_kg: Product weight in kg for shipping calculation
        commercial_use: Whether seeds are for commercial agricultural use (tax-exempt in Canada)
        
    Returns:
        Dictionary with detailed cost breakdown
    """
    if base_price <= 0:
        return {
            'base_price_cad': 0.0,
            'shipping_cad': 0.0,
            'duties_cad': 0.0,
            'taxes_cad': 0.0,
            'brokerage_cad': 0.0,
            'total_cad': 0.0,
            'markup_percentage': 0.0
        }
    
    # Exchange rates (approximate)
    exchange_rates = {
        'CAD': 1.0,
        'USD': 1.37
    }
    
    # Provincial tax rates (GST + PST/HST)
    provincial_tax_rates = {
        'BC': 0.12,  # 5% GST + 7% PST
        'AB': 0.05,  # 5% GST only
        'SK': 0.11,  # 5% GST + 6% PST
        'MB': 0.12,  # 5% GST + 7% PST
        'ON': 0.13,  # 13% HST
        'QC': 0.15,  # 5% GST + 9.975% QST
        'NB': 0.15,  # 15% HST
        'NS': 0.15,  # 15% HST
        'PE': 0.15,  # 15% HST
        'NL': 0.15,  # 15% HST
        'YT': 0.05,  # 5% GST only
        'NT': 0.05,  # 5% GST only
        'NU': 0.05   # 5% GST only
    }
    
    # Convert to CAD
    exchange_rate = exchange_rates.get(source_currency, 1.0)
    base_price_cad = base_price * exchange_rate
    
    # Calculate shipping
    if source_currency != 'CAD' and min_shipping > 0 and max_shipping > 0:
        # International shipping calculation
        if base_price < 25:
            shipping_source = min_shipping
        elif base_price > 400:
            shipping_source = max_shipping
        else:
            # Linear interpolation
            shipping_source = min_shipping + (base_price / 400) * (max_shipping - min_shipping)
        shipping_cad = shipping_source * exchange_rate
    elif source_currency == 'CAD' and weight_kg is not None:
        # Domestic shipping using weight-based Canada Post algorithm
        shipping_cad = calculate_canada_post_shipping(weight_kg)
    else:
        # No shipping for domestic suppliers without weight
        shipping_cad = 0.0
    
    # Duties (seeds are typically duty-free)
    duties_cad = 0.0
    
    # Taxes (on product value only, not shipping)
    # Seeds for commercial agricultural use are tax-exempt in Canada from Canadian suppliers
    if source_currency == 'CAD' and commercial_use:
        taxes_cad = 0.0  # Tax-exempt for commercial agricultural seeds from Canadian suppliers
    else:
        tax_rate = provincial_tax_rates.get(province.upper(), 0.13)  # Default to ON rate
        taxes_cad = base_price_cad * tax_rate
    
    # Brokerage (only for international shipments)
    brokerage_cad = brokerage_fee if source_currency != 'CAD' else 0.0
    
    # Total cost
    total_cad = base_price_cad + shipping_cad + duties_cad + taxes_cad + brokerage_cad
    
    # Markup percentage
    markup_percentage = ((total_cad - base_price_cad) / base_price_cad) * 100 if base_price_cad > 0 else 0.0
    
    return {
        'base_price_cad': round(base_price_cad, 2),
        'shipping_cad': round(shipping_cad, 2),
        'duties_cad': round(duties_cad, 2),
        'taxes_cad': round(taxes_cad, 2),
        'brokerage_cad': round(brokerage_cad, 2),
        'total_cad': round(total_cad, 2),
        'markup_percentage': round(markup_percentage, 1)
    }


def save_products_to_json(
    products: List[Dict[str, Any]], 
    output_dir: str, 
    filename_prefix: str,
    source_site: str,
    currency_code: str = "CAD",
    scrape_duration: float = 0.0,
    logger: Optional[logging.Logger] = None
) -> str:
    """
    Save products to JSON file with standardized format.
    
    Args:
        products: List of product dictionaries
        output_dir: Directory to save JSON file
        filename_prefix: Prefix for the filename
        source_site: URL of the source website
        currency_code: Currency code (default: CAD)
        scrape_duration: Time taken to scrape in seconds
        logger: Optional logger instance
        
    Returns:
        Path to saved JSON file
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate filename with timestamp only (since each scraper has its own directory)
    timestamp = datetime.now()
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp_str}.json"
    filepath = os.path.join(output_dir, filename)
    
    # Prepare data structure
    data = {
        "timestamp": timestamp.isoformat(),
        "scrape_duration_seconds": round(scrape_duration, 2),
        "source_site": source_site,
        "currency_code": currency_code,
        "product_count": len(products),
        "data": products
    }
    
    # Save to JSON
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    if logger:
        logger.info(f"Saved {len(products)} products to {filepath}")
    
    return filepath


def is_organic_product(title: str) -> bool:
    """
    Check if a product is organic based on its title.
    
    Args:
        title: Product title to check
        
    Returns:
        True if product contains organic indicators, False otherwise
    """
    if not title:
        return False
    
    title_lower = title.lower()
    organic_keywords = ['organic', 'biologique', 'bio ', ' bio']
    
    return any(keyword in title_lower for keyword in organic_keywords)


def validate_product_data(product: Dict[str, Any], logger: Optional[logging.Logger] = None) -> bool:
    """
    Validate product data for required fields and botanical naming conventions.
    
    Args:
        product: Product dictionary to validate
        logger: Optional logger instance
        
    Returns:
        True if valid, False otherwise
    """
    required_fields = ['title', 'url', 'is_in_stock', 'variations']
    
    # Check required fields
    for field in required_fields:
        if field not in product:
            if logger:
                logger.warning(f"Product missing required field '{field}': {product.get('title', 'Unknown')}")
            return False
    
    # Validate botanical naming conventions
    if 'common_name' in product:
        # Common names should be lowercase (except for proper nouns)
        common_name = product['common_name']
        if common_name and not is_valid_common_name(common_name):
            if logger:
                logger.warning(f"Invalid common name format '{common_name}' for product: {product.get('title')}")
        # Common names should be lowercase
        if common_name and common_name != common_name.lower():
            if logger:
                logger.info(f"Common name should be lowercase: '{common_name}' -> '{common_name.lower()}'")
    
    # Validate cultivar names - should be in single quotes per botanical convention
    if 'cultivar_name' in product and product['cultivar_name']:
        cultivar = product['cultivar_name']
        if cultivar and not (cultivar.startswith("'") and cultivar.endswith("'")):
            if logger:
                logger.warning(f"Cultivar name should be in single quotes per botanical convention: {cultivar}")
    
    # Validate variations
    if not product.get('variations'):
        if logger:
            logger.warning(f"Product has no variations: {product.get('title')}")
        return False
    
    for var in product['variations']:
        if 'price' not in var or var['price'] is None:
            if logger:
                logger.warning(f"Variation missing price: {product.get('title')} - {var.get('size')}")
        if 'weight_kg' in var and var['weight_kg'] is not None:
            if var['weight_kg'] <= 0:
                if logger:
                    logger.warning(f"Invalid weight for variation: {product.get('title')} - {var.get('size')}")
    
    return True


def is_valid_common_name(name: str) -> bool:
    """
    Check if a common name follows botanical naming conventions.
    
    Args:
        name: Common name to validate
        
    Returns:
        True if valid, False otherwise
    """
    # Common names should generally be lowercase except for proper nouns
    # This is a simplified check - could be expanded
    if not name:
        return False
    
    # List of acceptable capitalized words in common names
    proper_nouns = {'chinese', 'japanese', 'french', 'italian', 'thai', 'korean', 'swiss'}
    
    words = name.lower().split()
    return len(words) > 0 and all(word.isalpha() or word in proper_nouns for word in words)


def clean_text(text: str) -> str:
    """
    Clean text by removing extra whitespace and normalizing.
    
    Args:
        text: Text to clean
        
    Returns:
        Cleaned text
    """
    if not text:
        return ""
    
    # Remove extra whitespace
    text = ' '.join(text.split())
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    return text


def make_absolute_url(url: str, base_url: str) -> str:
    """
    Convert relative URL to absolute URL.
    
    Args:
        url: URL to convert (may be relative or absolute)
        base_url: Base URL for relative URLs
        
    Returns:
        Absolute URL
    """
    if not url:
        return ""
    
    # If already absolute, return as-is
    if url.startswith(('http://', 'https://')):
        return url
    
    # Otherwise, join with base URL
    return urljoin(base_url, url)


def get_domain_from_url(url: str) -> str:
    """
    Extract domain name from URL.
    
    Args:
        url: Full URL
        
    Returns:
        Domain name
    """
    parsed = urlparse(url)
    return parsed.netloc.replace('www.', '')


class ScraperError(Exception):
    """Base exception for scraper errors"""
    pass


class LoginError(ScraperError):
    """Exception raised when login fails"""
    pass


class ParseError(ScraperError):
    """Exception raised when parsing fails"""
    pass


class NetworkError(ScraperError):
    """Exception raised for network-related errors"""
    pass