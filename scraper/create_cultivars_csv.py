#!/usr/bin/env python3
import os
import csv
import json
import re
import logging
import logging.handlers
from datetime import datetime

# --- Constants ---
# Assuming this script is in the 'scraper' directory, and scraper_data is a sibling or defined path.
# Adjust if your directory structure is different or if running from a different CWD.
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError: # For environments where __file__ is not defined (e.g. some interactive interpreters)
    SCRIPT_DIR = os.getcwd()

WORKSPACE_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir)) # Moves up one level from scraper/ to workspace root
SCRAPER_DATA_DIR = os.path.join(WORKSPACE_ROOT, "scraper", "scraper_data")
SHARED_JSON_DIR = os.path.join(SCRAPER_DATA_DIR, "json_files")
CULTIVARS_CSV_FILEPATH = os.path.join(SCRAPER_DATA_DIR, "known_cultivars.csv")

LOG_DIR_FOR_UTIL = os.path.join(SCRIPT_DIR, "logs") # Logs for this utility script
LOG_FILE_FOR_UTIL = os.path.join(LOG_DIR_FOR_UTIL, "create_cultivars_csv.log")

DEFAULT_CULTIVARS = sorted(list(set([
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

# List of JSON files to source cultivar names from
# These paths are relative to SHARED_JSON_DIR
JSON_SOURCE_FILENAMES = [
    "sprouting_com_detailed_20250525_091908.json",
    "sprouting_com_detailed_20250526_082437.json",
    "germina_ca_organic_seeds_20250526_101029.json",
    "germina_ca_organic_seeds_20250526_104541.json",
    "damseeds_com_microgreens_atom_20250526_083255.json",
    "damseeds_com_microgreens_live_stock_20250526_090936.json"
]
JSON_SOURCES_FOR_CULTIVAR_EXTRACTION = [os.path.join(SHARED_JSON_DIR, fname) for fname in JSON_SOURCE_FILENAMES]


# --- Setup Logger ---
logger = logging.getLogger("CreateCultivarsCSV")
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
    logger.info("Logging configured for CreateCultivarsCSV Utility. Saving logs to: %s", LOG_FILE_FOR_UTIL)

# --- CSV and JSON Processing Functions ---

def save_known_cultivars_to_csv(filepath, cultivars_list):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        # Sort alphabetically for human readability in the CSV
        sorted_cultivars = sorted(list(set(c.strip() for c in cultivars_list if c and c.strip())))
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['cultivar_name']) # Header
            for cultivar in sorted_cultivars:
                writer.writerow([cultivar])
        logger.info(f"Saved {len(sorted_cultivars)} known cultivars to {filepath}")
    except Exception as e:
        logger.error(f"Error saving known cultivars to {filepath}: {e}")

def load_known_cultivars_from_csv(filepath, use_defaults_on_error=True):
    cultivars = []
    try:
        with open(filepath, 'r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            header = next(reader, None) # Skip header
            if header and header[0].lower().strip() != 'cultivar_name' and header[0].strip():
                 cultivars.append(header[0].strip()) # Not a header or empty, treat as data

            for row in reader:
                if row:
                    cultivar_name = row[0].strip()
                    if cultivar_name:
                        cultivars.append(cultivar_name)
        logger.info(f"Loaded {len(set(c for c in cultivars if c))} unique known cultivars from {filepath}")
    except FileNotFoundError:
        logger.warning(f"Known cultivars CSV not found at {filepath}.")
        if use_defaults_on_error:
            logger.info("Initializing with default list as CSV was not found.")
            cultivars = list(DEFAULT_CULTIVARS) 
            save_known_cultivars_to_csv(filepath, cultivars) # Create it with defaults
        else:
            cultivars = [] # Return empty if not using defaults
            
    except Exception as e:
        logger.error(f"Error loading known cultivars from {filepath}: {e}.")
        if use_defaults_on_error:
            logger.info("Using default list due to error.")
            cultivars = list(DEFAULT_CULTIVARS)
        else:
            cultivars = []

    unique_cultivars = sorted(list(set(c for c in cultivars if c)), key=len, reverse=True)
    
    if not unique_cultivars and use_defaults_on_error and DEFAULT_CULTIVARS:
        logger.warning(f"No valid cultivars loaded from {filepath} or CSV was empty. Re-initializing with defaults and saving.")
        unique_cultivars = sorted(list(set(c for c in DEFAULT_CULTIVARS if c)), key=len, reverse=True)
        save_known_cultivars_to_csv(filepath, unique_cultivars)
        
    return unique_cultivars


def update_cultivars_from_json_sources(json_filepaths, csv_filepath):
    logger.info(f"Starting update of known cultivars CSV from JSON sources. Target CSV: {csv_filepath}")
    # Load existing cultivars, or start with defaults if CSV doesn't exist or is empty
    existing_cultivars_from_csv = load_known_cultivars_from_csv(csv_filepath, use_defaults_on_error=True)
    combined_cultivars = set(c.title() for c in existing_cultivars_from_csv) # Use Title Case, ensure uniqueness

    newly_extracted_cultivars_candidates = set()

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
            
            products = data.get('data', [])
            if not isinstance(products, list):
                logger.warning(f"No 'data' list found or is not a list in {json_path}. Trying to read root as list.")
                if isinstance(data, list):
                    products = data
                else:
                    logger.error(f"Cannot find product list in {json_path}")
                    continue

            logger.info(f"Processing {len(products)} products from {json_path}")
            for product in products:
                title = product.get('title')
                if title and isinstance(title, str):
                    processed_title = re.sub(r'\\b(organic|biologique)\\b', '', title, flags=re.IGNORECASE).strip()
                    processed_title = ' '.join(processed_title.split())
                    
                    candidate = processed_title
                    delimiters = [',', '-']
                    for delimiter in delimiters:
                        if delimiter in processed_title:
                            parts = processed_title.split(delimiter, 1)
                            if parts[0].strip():
                                candidate = parts[0].strip()
                                break
                    
                    if candidate:
                        candidate_lower = candidate.lower()
                        if candidate_lower.endswith(" seeds"): candidate = candidate[:-len(" seeds")].strip()
                        elif candidate_lower.endswith(" seed"): candidate = candidate[:-len(" seed")].strip()
                        
                        # Avoid adding very short strings or pure numbers
                        if candidate and len(candidate) > 2 and not candidate.isdigit():
                             # Heuristic: if it contains a number, it might be a variety, not a base cultivar.
                             # e.g. "4010 Green Forage Pea". "4010 Green Forage Pea" is not a good general cultivar.
                             # We want "Pea".
                             # This is tricky. For now, let's add them and user can prune CSV.
                            newly_extracted_cultivars_candidates.add(candidate.title())
                                                        
        except json.JSONDecodeError as jde:
            logger.error(f"Error decoding JSON from {json_path}: {jde}")
        except Exception as e:
            logger.error(f"Error processing file {json_path}: {e}")

    added_count = 0
    if newly_extracted_cultivars_candidates:
        logger.info(f"Extracted {len(newly_extracted_cultivars_candidates)} potential unique cultivar names from JSON sources.")
        for new_cult_candidate in newly_extracted_cultivars_candidates:
            # Check if the candidate itself or any part of it (if multi-word) matches a default cultivar.
            # This helps to avoid adding "Red Rubin Basil" if "Basil" is already a default/known cultivar.
            # We are trying to get base cultivars.
            is_already_covered_by_default = False
            candidate_parts = set(p.lower() for p in new_cult_candidate.split())
            for def_cult in DEFAULT_CULTIVARS:
                if def_cult.lower() in candidate_parts:
                    is_already_covered_by_default = True
                    break
            
            # Add to combined_cultivars if it's not too generic and not already covered by a very common default.
            # The goal is to expand the list with meaningful specific cultivars not just variations of defaults.
            # This logic might need refinement based on results.
            # For now, we add if it's not directly a default cultivar itself (case insensitive).
            if new_cult_candidate.lower() not in (c.lower() for c in DEFAULT_CULTIVARS):
                if new_cult_candidate.lower() not in (c.lower() for c in combined_cultivars):
                    combined_cultivars.add(new_cult_candidate)
                    added_count += 1
        
        if added_count > 0:
            logger.info(f"Adding {added_count} new unique cultivars to the list.")
        else:
            logger.info("No new unique cultivars (not covered by defaults) to add to the CSV from JSON data, or they were already present.")
    else:
        logger.info("No potential cultivars extracted from JSON sources.")

    # Always save, even if only defaults were used or no new ones added from JSON,
    # to ensure CSV exists and is formatted.
    save_known_cultivars_to_csv(csv_filepath, list(combined_cultivars))
    logger.info("Cultivar CSV update process finished. File is at: %s", csv_filepath)

# --- Main Execution ---
if __name__ == "__main__":
    setup_logging_for_util()
    logger.info("Starting Known Cultivars CSV creation/update utility.")
    
    # Ensure the target directory for CSV exists
    os.makedirs(os.path.dirname(CULTIVARS_CSV_FILEPATH), exist_ok=True)
    
    update_cultivars_from_json_sources(JSON_SOURCES_FOR_CULTIVAR_EXTRACTION, CULTIVARS_CSV_FILEPATH)
    
    logger.info("Script finished. Check the log and the CSV file.") 