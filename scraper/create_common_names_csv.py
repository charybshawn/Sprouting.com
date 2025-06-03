#!/usr/bin/env python3
import os
import csv
import json
import re
import logging
import logging.handlers
from datetime import datetime
import seed_naming_utils

# --- Constants ---
# Assuming this script is in the 'scraper' directory, and scraper_data is a sibling or defined path.
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError: # For environments where __file__ is not defined (e.g. some interactive interpreters)
    SCRIPT_DIR = os.getcwd()

WORKSPACE_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir)) # Moves up one level from scraper/ to workspace root
SCRAPER_DATA_DIR = os.path.join(WORKSPACE_ROOT, "scraper_data")
SHARED_JSON_DIR = os.path.join(SCRAPER_DATA_DIR, "json_files")
COMMON_NAMES_CSV_FILEPATH = os.path.join(SCRAPER_DATA_DIR, "common_names.csv")
CULTIVARS_CSV_FILEPATH = os.path.join(SCRAPER_DATA_DIR, "cultivars.csv")

LOG_DIR_FOR_UTIL = os.path.join(SCRIPT_DIR, "logs") # Logs for this utility script
LOG_FILE_FOR_UTIL = os.path.join(LOG_DIR_FOR_UTIL, "create_common_names_csv.log")

# Default common names for microgreens/sprouting seeds
DEFAULT_COMMON_NAMES = sorted(list(set([
    "Alfalfa", "Amaranth", "Arugula", "Barley", "Basil", "Beet", "Bok Choy", "Borage",
    "Broccoli", "Buckwheat", "Cabbage", "Carrot", "Celery", "Chervil", "Chia", "Chicory",
    "Cilantro", "Clover", "Collard", "Coriander", "Corn Salad", "Cress", "Dill",
    "Endive", "Fava Bean", "Fennel", "Fenugreek", "Flax", "Garlic Chives", "Kale",
    "Kamut", "Kohlrabi", "Komatsuna", "Leek", "Lemon Balm", "Lentil", "Lettuce",
    "Mache", "Melon", "Millet", "Mizuna", "Mung Bean", "Mustard", "Nasturtium", "Oat",
    "Okra", "Onion", "Pak Choi", "Parsley", "Pea", "Peppergrass", "Perilla", "Popcorn",
    "Poppy", "Purslane", "Quinoa", "Radish", "Rapini", "Red Shiso", "Rice", "Rocket",
    "Rutabaga", "Rye", "Shiso", "Sorrel", "Spelt", "Spinach", "Sunflower", "Swiss Chard",
    "Tatsoi", "Thyme", "Turnip", "Watercress", "Wheat", "Wheatgrass"
])))

# List of JSON files to source seed names from
# Define your JSON source filenames below, or all .json files will be processed if found
JSON_SOURCE_FILENAMES = [
    # Add specific filenames here if needed
    # "sprouting_com_detailed_20250525_091908.json",
    # "germina_ca_organic_seeds_20250526_101029.json",
]

# Get full paths for JSON sources
JSON_SOURCES_FOR_EXTRACTION = []
if JSON_SOURCE_FILENAMES:
    # Use specified filenames
    for filename in JSON_SOURCE_FILENAMES:
        json_path = os.path.join(SHARED_JSON_DIR, filename)
        if os.path.exists(json_path):
            JSON_SOURCES_FOR_EXTRACTION.append(json_path)
else:
    # Find all JSON files recursively
    for root, dirs, files in os.walk(SHARED_JSON_DIR):
        for file in files:
            if file.endswith('.json'):
                JSON_SOURCES_FOR_EXTRACTION.append(os.path.join(root, file))

# --- Setup Logger ---
logger = logging.getLogger("CreateCommonNamesCSV")
logger.setLevel(logging.INFO)

def setup_logging_for_util():
    """Configures logging for this utility script."""
    if not os.path.exists(LOG_DIR_FOR_UTIL):
        try:
            os.makedirs(LOG_DIR_FOR_UTIL)
        except OSError as e:
            print(f"Error creating log directory {LOG_DIR_FOR_UTIL}: {e}")
            logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
            return

    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(message)s')

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE_FOR_UTIL, maxBytes=1*1024*1024, backupCount=3, encoding='utf-8'
        )
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Error setting up file logger for utility: {e}")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)
    logger.info("Logging configured for CreateCommonNamesCSV Utility. Saving logs to: %s", LOG_FILE_FOR_UTIL)

# --- CSV and JSON Processing Functions ---

def save_common_names_to_csv(filepath, names_list):
    """Save a list of common names to a CSV file."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        # Sort alphabetically for human readability in the CSV
        sorted_names = sorted(list(set(n.strip() for n in names_list if n and n.strip())))
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['common_name']) # Header
            for name in sorted_names:
                writer.writerow([name])
        logger.info(f"Saved {len(sorted_names)} common names to {filepath}")
    except Exception as e:
        logger.error(f"Error saving common names to {filepath}: {e}")

def save_cultivars_to_csv(filepath, cultivars_dict):
    """
    Save cultivars to a CSV file, organized by common name.
    
    Args:
        filepath (str): Path to the CSV file
        cultivars_dict (dict): Dictionary with common names as keys and lists of cultivars as values
    """
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['common_name', 'cultivar_name']) # Header
            
            # Sort by common name for readability
            for common_name in sorted(cultivars_dict.keys()):
                # Sort cultivars for each common name
                cultivars = sorted(list(set(cultivars_dict[common_name])))
                for cultivar in cultivars:
                    writer.writerow([common_name, cultivar])
        
        # Count total unique cultivars
        total_cultivars = sum(len(set(cultivars)) for cultivars in cultivars_dict.values())
        logger.info(f"Saved {total_cultivars} cultivars for {len(cultivars_dict)} common names to {filepath}")
    except Exception as e:
        logger.error(f"Error saving cultivars to {filepath}: {e}")

def load_common_names_from_csv(filepath, use_defaults_on_error=True):
    """Load common names from a CSV file."""
    common_names = []
    try:
        with open(filepath, 'r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            header = next(reader, None) # Skip header
            if header and header[0].lower().strip() != 'common_name' and header[0].strip():
                 common_names.append(header[0].strip()) # Not a header or empty, treat as data

            for row in reader:
                if row:
                    name = row[0].strip()
                    if name:
                        common_names.append(name)
        logger.info(f"Loaded {len(set(n for n in common_names if n))} unique common names from {filepath}")
    except FileNotFoundError:
        logger.warning(f"Common names CSV not found at {filepath}.")
        if use_defaults_on_error:
            logger.info("Initializing with default list as CSV was not found.")
            common_names = list(DEFAULT_COMMON_NAMES) 
            save_common_names_to_csv(filepath, common_names) # Create it with defaults
        else:
            common_names = [] # Return empty if not using defaults
            
    except Exception as e:
        logger.error(f"Error loading common names from {filepath}: {e}.")
        if use_defaults_on_error:
            logger.info("Using default list due to error.")
            common_names = list(DEFAULT_COMMON_NAMES)
        else:
            common_names = []

    unique_common_names = sorted(list(set(n for n in common_names if n)))
    
    if not unique_common_names and use_defaults_on_error and DEFAULT_COMMON_NAMES:
        logger.warning(f"No valid common names loaded from {filepath} or CSV was empty. Re-initializing with defaults and saving.")
        unique_common_names = sorted(list(set(n for n in DEFAULT_COMMON_NAMES if n)))
        save_common_names_to_csv(filepath, unique_common_names)
        
    return unique_common_names


def update_seed_names_from_json_sources(json_filepaths, common_names_csv_path, cultivars_csv_path):
    """
    Extract common names and cultivars from JSON sources and update the CSV files.
    
    Args:
        json_filepaths (list): List of JSON file paths to process
        common_names_csv_path (str): Path to save common names CSV
        cultivars_csv_path (str): Path to save cultivars CSV
    """
    logger.info(f"Starting update of seed naming CSVs from JSON sources.")
    
    # Load existing common names, or start with defaults if CSV doesn't exist or is empty
    existing_common_names = load_common_names_from_csv(common_names_csv_path, use_defaults_on_error=True)
    combined_common_names = set(n.title() for n in existing_common_names)  # Use Title Case for consistency
    
    # Dictionary to store cultivars by common name
    cultivars_by_common_name = {}
    
    # Process each JSON file
    for json_path in json_filepaths:
        if not os.path.exists(json_path):
            logger.warning(f"JSON source file not found, skipping: {json_path}")
            continue
            
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content.strip():
                    logger.warning(f"JSON file is empty, skipping: {json_path}")
                    continue
                data = json.loads(content)
            
            # Extract the product list
            products = data.get('data', [])
            if not isinstance(products, list):
                logger.warning(f"No 'data' list found or is not a list in {json_path}. Trying to read root as list.")
                if isinstance(data, list):
                    products = data
                else:
                    logger.error(f"Cannot find product list in {json_path}")
                    continue
            
            logger.info(f"Processing {len(products)} products from {json_path}")
            
            # Process each product
            for product in products:
                # Handle both new and old field naming conventions
                title = product.get('title')
                if title and isinstance(title, str):
                    # Parse the seed name using our utility
                    parsed = seed_naming_utils.parse_seed_name(title, existing_common_names)
                    common_name = parsed['common_name']
                    cultivar_name = parsed['cultivar_name']
                    
                    # Add to combined common names
                    if common_name != "N/A":
                        combined_common_names.add(common_name.title())
                    
                    # Add to cultivars dictionary
                    if common_name != "N/A" and cultivar_name != "N/A":
                        if common_name not in cultivars_by_common_name:
                            cultivars_by_common_name[common_name] = set()
                        cultivars_by_common_name[common_name].add(cultivar_name)
                    
                    # Also check if the product has the old format fields
                    old_cultivar = product.get('cultivar')
                    old_plant_variety = product.get('plant_variety')
                    
                    if old_cultivar and old_cultivar != "N/A" and isinstance(old_cultivar, str):
                        # Treat old 'cultivar' field as common_name if it looks like a common name
                        if old_cultivar.lower() in [name.lower() for name in existing_common_names]:
                            combined_common_names.add(old_cultivar.title())
                            
                            # If we also have a plant_variety, add it as a cultivar
                            if old_plant_variety and old_plant_variety != "N/A" and isinstance(old_plant_variety, str):
                                if old_cultivar not in cultivars_by_common_name:
                                    cultivars_by_common_name[old_cultivar] = set()
                                cultivars_by_common_name[old_cultivar].add(old_plant_variety)
        
        except json.JSONDecodeError as jde:
            logger.error(f"Error decoding JSON from {json_path}: {jde}")
        except Exception as e:
            logger.error(f"Error processing file {json_path}: {e}")
    
    # Save updated common names to CSV
    save_common_names_to_csv(common_names_csv_path, list(combined_common_names))
    
    # Save cultivars to CSV
    save_cultivars_to_csv(cultivars_csv_path, cultivars_by_common_name)
    
    logger.info("Seed naming CSV update process finished.")
    logger.info(f"Common names CSV saved to: {common_names_csv_path}")
    logger.info(f"Cultivars CSV saved to: {cultivars_csv_path}")


# --- Main Execution ---
if __name__ == "__main__":
    setup_logging_for_util()
    logger.info("Starting Common Names and Cultivars CSV creation/update utility.")
    
    # Ensure the target directories for CSVs exist
    os.makedirs(os.path.dirname(COMMON_NAMES_CSV_FILEPATH), exist_ok=True)
    os.makedirs(os.path.dirname(CULTIVARS_CSV_FILEPATH), exist_ok=True)
    
    # Update seed names from JSON sources
    update_seed_names_from_json_sources(
        JSON_SOURCES_FOR_EXTRACTION, 
        COMMON_NAMES_CSV_FILEPATH,
        CULTIVARS_CSV_FILEPATH
    )
    
    logger.info("Script finished. Check the log and the CSV files.") 