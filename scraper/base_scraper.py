"""
Abstract base class for all scrapers in the Sprouting.com project.
Provides common functionality and interface for concrete scraper implementations.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
import os
import time
from datetime import datetime
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from scraper_utils import (
    setup_logging, save_products_to_json, validate_product_data,
    ScraperError, LoginError, ParseError, NetworkError
)


class BaseScraper(ABC):
    """Abstract base class for all product scrapers."""
    
    def __init__(
        self, 
        supplier_name: str,
        source_site: str,
        output_dir: str,
        currency_code: str = "CAD",
        headless: bool = True,
        test_mode: bool = False,
        test_limit: int = 2
    ):
        """
        Initialize the base scraper.
        
        Args:
            supplier_name: Name of the supplier (used for logging and file naming)
            source_site: Base URL of the source website
            output_dir: Directory to save output JSON files
            currency_code: Currency code for prices
            headless: Whether to run browser in headless mode
            test_mode: Whether to run in test mode (limited scraping)
            test_limit: Number of products to scrape in test mode
        """
        self.supplier_name = supplier_name
        self.source_site = source_site
        self.output_dir = output_dir
        self.currency_code = currency_code
        self.headless = headless
        self.test_mode = test_mode
        self.test_limit = test_limit
        
        # Setup logger
        self.logger = setup_logging(f"{supplier_name}_scraper")
        
        # Browser components (initialized in context manager)
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        # Timing
        self.start_time: Optional[float] = None
        
    def __enter__(self):
        """Context manager entry - initialize browser."""
        self.start_time = time.time()
        self.logger.info(f"Starting {self.supplier_name} scraper")
        
        # Initialize playwright and browser
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.context = self.browser.new_context(
            user_agent=self.get_user_agent(),
            java_script_enabled=True,
            accept_downloads=False,
        )
        self.page = self.context.new_page()
        
        # Perform any necessary login
        if self.requires_login():
            self.login()
            
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup browser."""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
            
        duration = time.time() - self.start_time if self.start_time else 0
        self.logger.info(f"{self.supplier_name} scraper finished. Duration: {duration:.2f} seconds")
        
    def get_user_agent(self) -> str:
        """Get user agent string for browser."""
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
    def requires_login(self) -> bool:
        """Override this method if scraper requires login."""
        return False
        
    def login(self) -> None:
        """Override this method to implement login logic."""
        pass
        
    @abstractmethod
    def fetch_product_list(self) -> List[Dict[str, Any]]:
        """
        Fetch the list of products to scrape.
        This could be from an API, feed, or by navigating pages.
        
        Returns:
            List of product dictionaries with at least 'url' and 'title'
        """
        pass
        
    @abstractmethod
    def scrape_product_details(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scrape detailed information for a single product.
        
        Args:
            product: Product dictionary from fetch_product_list
            
        Returns:
            Complete product dictionary with all required fields
        """
        pass
        
    def process_products(self, products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process a list of products, applying test mode limits if needed.
        
        Args:
            products: List of products to process
            
        Returns:
            List of processed products
        """
        if self.test_mode and len(products) > self.test_limit:
            self.logger.info(f"TEST_MODE: Limiting to {self.test_limit} products")
            products = products[:self.test_limit]
            
        return products
        
    def scrape(self) -> List[Dict[str, Any]]:
        """
        Main scraping method that orchestrates the entire process.
        
        Returns:
            List of scraped product dictionaries
        """
        try:
            # Fetch product list
            self.logger.info("Fetching product list...")
            products = self.fetch_product_list()
            self.logger.info(f"Found {len(products)} products")
            
            # Apply test mode limits
            products = self.process_products(products)
            
            # Scrape details for each product
            detailed_products = []
            for i, product in enumerate(products, 1):
                self.logger.info(f"Processing product {i}/{len(products)}: {product.get('title', 'Unknown')}")
                
                try:
                    # Add politeness delay
                    if i > 1:
                        time.sleep(self.get_politeness_delay())
                        
                    # Scrape product details
                    detailed_product = self.scrape_product_details(product)
                    
                    # Validate product data
                    if validate_product_data(detailed_product, self.logger):
                        detailed_products.append(detailed_product)
                    else:
                        self.logger.warning(f"Product failed validation: {product.get('title')}")
                        
                except Exception as e:
                    self.logger.error(f"Error scraping product {product.get('title')}: {e}", exc_info=True)
                    continue
                    
            return detailed_products
            
        except Exception as e:
            self.logger.error(f"Fatal error during scraping: {e}", exc_info=True)
            raise ScraperError(f"Scraping failed: {e}")
            
    def get_politeness_delay(self) -> float:
        """Get delay between requests in seconds. Override to customize."""
        return 1.0
        
    def save_results(self, products: List[Dict[str, Any]], filename_prefix: Optional[str] = None) -> str:
        """
        Save scraped products to JSON file.
        
        Args:
            products: List of product dictionaries
            filename_prefix: Optional prefix for filename
            
        Returns:
            Path to saved file
        """
        if not filename_prefix:
            filename_prefix = f"{self.supplier_name}_products"
            
        duration = time.time() - self.start_time if self.start_time else 0
        
        return save_products_to_json(
            products=products,
            output_dir=self.output_dir,
            filename_prefix=filename_prefix,
            source_site=self.source_site,
            currency_code=self.currency_code,
            scrape_duration=duration,
            logger=self.logger
        )
        
    def run(self) -> None:
        """
        Convenience method to run the scraper with context management.
        """
        with self:
            products = self.scrape()
            if products:
                output_file = self.save_results(products)
                self.logger.info(f"Scraping complete. {len(products)} products saved to {output_file}")
            else:
                self.logger.warning("No products were scraped")


class FeedBasedScraper(BaseScraper):
    """
    Base class for scrapers that use feeds (Atom, RSS, JSON API).
    Provides additional methods for feed-based scraping patterns.
    """
    
    @abstractmethod
    def fetch_feed(self) -> Any:
        """
        Fetch the feed content (XML, JSON, etc).
        
        Returns:
            Feed content in appropriate format
        """
        pass
        
    @abstractmethod
    def parse_feed(self, feed_content: Any) -> List[Dict[str, Any]]:
        """
        Parse the feed content into a list of products.
        
        Args:
            feed_content: Raw feed content
            
        Returns:
            List of product dictionaries
        """
        pass
        
    def fetch_product_list(self) -> List[Dict[str, Any]]:
        """
        Implementation of fetch_product_list for feed-based scrapers.
        """
        feed_content = self.fetch_feed()
        return self.parse_feed(feed_content)
        
    def update_stock_status(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update stock status by visiting the product page.
        Override this method to implement custom stock checking logic.
        
        Args:
            product: Product dictionary with at least 'url' field
            
        Returns:
            Updated product dictionary with stock information
        """
        # Default implementation - override in subclasses
        product['is_in_stock'] = False
        for variation in product.get('variations', []):
            variation['is_variation_in_stock'] = False
        return product


class PageNavigationScraper(BaseScraper):
    """
    Base class for scrapers that navigate through pages (pagination, categories).
    Provides methods for page-based scraping patterns.
    """
    
    @abstractmethod
    def get_start_urls(self) -> List[str]:
        """
        Get the list of starting URLs to scrape.
        
        Returns:
            List of URLs to start scraping from
        """
        pass
        
    @abstractmethod
    def extract_product_links(self, page_url: str) -> List[Dict[str, Any]]:
        """
        Extract product links from a listing page.
        
        Args:
            page_url: URL of the listing page
            
        Returns:
            List of product dictionaries with at least 'url' and 'title'
        """
        pass
        
    def get_next_page_url(self, current_url: str) -> Optional[str]:
        """
        Get the URL of the next page, if any.
        Override this method to implement pagination.
        
        Args:
            current_url: Current page URL
            
        Returns:
            Next page URL or None if no more pages
        """
        return None
        
    def fetch_product_list(self) -> List[Dict[str, Any]]:
        """
        Implementation of fetch_product_list for page-based scrapers.
        """
        all_products = []
        
        for start_url in self.get_start_urls():
            current_url = start_url
            page_num = 1
            
            while current_url:
                self.logger.info(f"Fetching page {page_num}: {current_url}")
                
                try:
                    products = self.extract_product_links(current_url)
                    all_products.extend(products)
                    
                    # Check for next page
                    current_url = self.get_next_page_url(current_url)
                    page_num += 1
                    
                    # Add delay between pages
                    if current_url:
                        time.sleep(self.get_politeness_delay())
                        
                except Exception as e:
                    self.logger.error(f"Error fetching page {current_url}: {e}", exc_info=True)
                    break
                    
        return all_products