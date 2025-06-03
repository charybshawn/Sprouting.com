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
        'kilogram': 1.0,
        'kilograms': 1.0,
        'g': 0.001,
        'gr': 0.001,
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
    
    # Try different patterns
    patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:x\s*)?(\d+(?:\.\d+)?)\s*(kg|kgs|g|gr|gram|grams|lb|lbs|pound|pounds|oz|ounce|ounces)',
        r'(\d+(?:\.\d+)?)\s*(kg|kgs|g|gr|gram|grams|lb|lbs|pound|pounds|oz|ounce|ounces)',
        r'(\d+(?:\.\d+)?)\s*(?:x\s*)?(\d+(?:\.\d+)?)\s*(?:kilogram|kilograms)',
        r'(\d+(?:\.\d+)?)\s*(?:kilogram|kilograms)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, weight_str)
        if match:
            groups = match.groups()
            if len(groups) == 3:  # Multiple weights (e.g., "5 x 500g")
                quantity = float(groups[0])
                weight = float(groups[1])
                unit = groups[2]
                total_weight = quantity * weight
            elif len(groups) == 2:  # Single weight
                total_weight = float(groups[0])
                unit = groups[1]
            else:
                continue
                
            # Convert to kg
            if unit in conversions:
                weight_kg = total_weight * conversions[unit]
                return weight_kg, total_weight, unit
            elif 'kilogram' in str(groups[-1]):
                return total_weight, total_weight, 'kg'
    
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
    
    # Common replacements
    replacements = {
        ' gram': 'g',
        ' grams': 'g',
        ' kilogram': ' kg',
        ' kilograms': ' kg',
        ' pound': ' lb',
        ' pounds': ' lb',
        ' ounce': ' oz',
        ' ounces': ' oz',
        'gram ': 'g ',
        'grams ': 'g ',
        'kilogram ': 'kg ',
        'kilograms ': 'kg ',
    }
    
    for old, new in replacements.items():
        size_str = size_str.replace(old, new)
    
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
    
    # Generate filename with timestamp
    timestamp = datetime.now()
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
    filename = f"{filename_prefix}_{timestamp_str}.json"
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