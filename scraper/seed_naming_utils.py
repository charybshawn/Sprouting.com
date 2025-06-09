#!/usr/bin/env python3
import re
import os
import csv
import logging

logger = logging.getLogger("SeedNamingUtils")

# Dictionary mapping common names to their formal names for consistency
COMMON_NAME_MAPPING = {
    "swiss chard": "Swiss Chard",
    "chard": "Swiss Chard",
    "kale": "Kale",
    "radish": "Radish",
    "winter radish": "Radish",
    "broccoli": "Broccoli",
    "sunflower": "Sunflower",
    "pea": "Pea",
    "peas": "Pea",
    "alfalfa": "Alfalfa",
    "mustard": "Mustard",
    "arugula": "Arugula",
    "lettuce": "Lettuce",
    "beet": "Beet",
    "beets": "Beet",
    "spinach": "Spinach",
    "basil": "Basil",
    "amaranth": "Amaranth",
    "buckwheat": "Buckwheat",
    "chia": "Chia",
    "cilantro": "Cilantro",
    "coriander": "Coriander",
    "cress": "Cress",
    "peppergrass": "Cress",
    "garden cress": "Cress",
    "mung bean": "Mung Bean",
    "bean": "Bean",
    "wheatgrass": "Wheatgrass",
    "clover": "Clover",
    "cabbage": "Cabbage",
    "collard": "Collard",
    "corn": "Corn",
    "barley": "Barley",
    "oat": "Oat",
    "dill": "Dill",
    "fava bean": "Fava Bean",
    "fennel": "Fennel",
    "fenugreek": "Fenugreek",
    "flax": "Flax",
    "kohlrabi": "Kohlrabi",
    "leek": "Leek",
    "lentil": "Lentil",
    "mizuna": "Mizuna",
    "komatsuna": "Komatsuna",
    "nasturtium": "Nasturtium",
    "onion": "Onion",
    "onions": "Onion",
    "parsley": "Parsley",
    "quinoa": "Quinoa",
    "rutabaga": "Rutabaga",
    "rye": "Rye",
    "sorrel": "Sorrel",
    "thyme": "Thyme",
    "turnip": "Turnip",
    "watercress": "Watercress",
    "wheat": "Wheat",
    "forage pea": "Pea",
    "green forage pea": "Pea",
    "green pea": "Pea",
    "chervil": "Chervil",
    # Note: "greens" removed from mapping - handled specially in comma-separated logic
    # Add more mappings as needed
}

# Keywords that indicate a cultivar rather than a common name
CULTIVAR_INDICATORS = [
    "greencrops",
    "4010",
]

def load_known_common_names(csv_path):
    """
    Load known common names from a CSV file.
    Returns a list of common names in title case.
    """
    common_names = []
    try:
        with open(csv_path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            header = next(reader, None)  # Skip header
            for row in reader:
                if row:
                    name = row[0].strip()
                    if name:
                        common_names.append(name.title())
        logger.info(f"Loaded {len(common_names)} common names from {csv_path}")
    except FileNotFoundError:
        logger.warning(f"Common names CSV not found at {csv_path}")
    except Exception as e:
        logger.error(f"Error loading common names from {csv_path}: {e}")
    
    return common_names

def _parse_seed_name_internal(product_title, known_common_names=None):
    """Internal parsing function without cleaning."""
    if not product_title:
        return {
            "common_name": "N/A",
            "cultivar_name": "N/A", 
            "additional_descriptors": "N/A"
        }
    
    # Remove "organic" or "biologique" and clean up whitespace
    processed_title = re.sub(r'\b(organic|biologique)\b', '', product_title, flags=re.IGNORECASE).strip()
    processed_title = ' '.join(processed_title.split())  # Normalize spaces
    
    # Remove "seeds" or "seed" from the end
    processed_title = re.sub(r'\s+(seeds|seed)$', '', processed_title, flags=re.IGNORECASE).strip()
    
    # Clean trailing commas and extra spaces from the title
    processed_title = re.sub(r',\s*$', '', processed_title).strip()
    
    # Special case for titles like "Greencrops, 4010 Green Forage Pea - Organic"
    # Check for known common names embedded in the title
    for key, value in COMMON_NAME_MAPPING.items():
        if re.search(r'\b' + re.escape(key) + r'\b', processed_title, re.IGNORECASE):
            # Found a common name within the title
            # Check if this is a special case with a cultivar indicator at the beginning
            for indicator in CULTIVAR_INDICATORS:
                if re.search(r'\b' + re.escape(indicator) + r'\b', processed_title, re.IGNORECASE):
                    # This appears to be a title with a cultivar indicator and an embedded common name
                    # Extract the cultivar part (anything before the common name or between commas/dashes)
                    cultivar_part = ""
                    
                    # Try splitting by commas first
                    if ',' in processed_title:
                        parts = processed_title.split(',', 1)
                        cultivar_part = parts[0].strip()
                        remaining = parts[1].strip()
                    else:
                        # Otherwise try to find the cultivar part before the common name
                        pattern = re.compile(r'(.+?)\s+\b' + re.escape(key) + r'\b', re.IGNORECASE)
                        match = pattern.search(processed_title)
                        if match:
                            cultivar_part = match.group(1).strip()
                            # Get the rest of the string after the match
                            remaining = processed_title[match.end():].strip()
                        else:
                            # If no clear cultivar part is found, use the whole title
                            remaining = processed_title
                    
                    # Extract additional descriptors if any (after common name or dash)
                    descriptors = "N/A"
                    if '-' in remaining:
                        parts = remaining.split('-', 1)
                        descriptors = parts[1].strip() if parts[1].strip() else "N/A"
                    
                    return {
                        "common_name": value,
                        "cultivar_name": cultivar_part if cultivar_part else "N/A",
                        "additional_descriptors": descriptors
                    }
    
    # Step 1: Check for cultivar notation with single quotes
    cultivar_match = re.search(r"'([^']+)'", processed_title)
    if cultivar_match:
        cultivar_name = cultivar_match.group(1)
        # Remove the cultivar from the title to help identify the common name
        remaining_text = processed_title.replace(f"'{cultivar_name}'", "").strip()
        
        # Try to extract common name from remaining text
        common_name = extract_common_name(remaining_text, known_common_names)
        additional_descriptors = extract_additional_descriptors(remaining_text, common_name)
        
        return {
            "common_name": common_name,
            "cultivar_name": cultivar_name,
            "additional_descriptors": additional_descriptors
        }
    
    # Step 2: Look for a comma or dash separator that might separate common name and cultivar
    split_chars = [',', '-']
    for char in split_chars:
        if char in processed_title:
            parts = processed_title.split(char, 1)
            
            # Check if the first part is a known common name
            left_part = parts[0].strip()
            right_part = parts[1].strip() if len(parts) > 1 else ""
            
            # Clean trailing commas from parts before processing
            left_part = re.sub(r',\s*$', '', left_part).strip()
            right_part = re.sub(r'^\s*,', '', right_part).strip()
            
            # If left part is a known common name or matches our mapping
            if is_common_name(left_part, known_common_names):
                common_name = standardize_common_name(left_part)
                # Check if right part could be a cultivar (usually capitalized words)
                if right_part and any(word[0].isupper() for word in right_part.split() if word and len(word) > 1):
                    # Further split the right part if it contains another comma or dash
                    right_split = None
                    for split_char in split_chars:
                        if split_char in right_part:
                            right_parts = right_part.split(split_char, 1)
                            right_split = (right_parts[0].strip(), right_parts[1].strip())
                            break
                    
                    if right_split:
                        return {
                            "common_name": common_name,
                            "cultivar_name": right_split[0],
                            "additional_descriptors": right_split[1] if right_split[1] else "N/A"
                        }
                    else:
                        return {
                            "common_name": common_name,
                            "cultivar_name": right_part,
                            "additional_descriptors": "N/A"
                        }
                else:
                    # If right part doesn't look like a cultivar, it's probably descriptors
                    return {
                        "common_name": common_name,
                        "cultivar_name": "N/A",
                        "additional_descriptors": right_part if right_part else "N/A"
                    }
            
            # Special case: Handle "Greens," prefix pattern that indicates the common name is in the right part
            if left_part.lower().strip() == "greens":
                # Check for specific plant names FIRST before checking mapping
                if 'amaranth' in right_part.lower():
                    # Extract cultivar from titles like "Red Garnet Amaranth"
                    amaranth_match = re.search(r'(.+?)\s+amaranth', right_part, re.IGNORECASE)
                    if amaranth_match:
                        cultivar = amaranth_match.group(1).strip()
                        return {"common_name": "Amaranth", "cultivar_name": cultivar, "additional_descriptors": "N/A"}
                    else:
                        return {"common_name": "Amaranth", "cultivar_name": "N/A", "additional_descriptors": "N/A"}
                elif 'mizuna' in right_part.lower():
                    return {"common_name": "Mizuna", "cultivar_name": "N/A", "additional_descriptors": "N/A"}
                elif 'komatsuna' in right_part.lower():
                    return {"common_name": "Komatsuna", "cultivar_name": "N/A", "additional_descriptors": "N/A"}
                elif 'garden cress' in right_part.lower() or 'peppergrass' in right_part.lower():
                    return {"common_name": "Cress", "cultivar_name": "Peppergrass", "additional_descriptors": "N/A"}
                
                # Look for actual common name in the right part (longest match first)
                sorted_mapping = sorted(COMMON_NAME_MAPPING.items(), key=lambda x: len(x[0]), reverse=True)
                for key, value in sorted_mapping:
                    if re.search(r'\b' + re.escape(key) + r'\b', right_part, re.IGNORECASE):
                        # Remove the matched common name from right part to get cultivar
                        remaining_right = re.sub(r'\b' + re.escape(key) + r'\b', '', right_part, flags=re.IGNORECASE).strip()
                        remaining_right = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', remaining_right).strip()  # Clean punctuation
                        return {
                            "common_name": value,
                            "cultivar_name": remaining_right if remaining_right else "N/A",
                            "additional_descriptors": "N/A"
                        }
                
                # If no specific mapping found, treat the right part as the common name
                return {
                    "common_name": right_part.title(),
                    "cultivar_name": "N/A", 
                    "additional_descriptors": "N/A"
                }
            
            # If the first part is not a common name, check if it's a cultivar indicator
            # and look for common names in the right part
            for indicator in CULTIVAR_INDICATORS:
                if re.search(r'\b' + re.escape(indicator) + r'\b', left_part, re.IGNORECASE):
                    # This is likely a cultivar indicator, search for common name in right part
                    for key, value in COMMON_NAME_MAPPING.items():
                        if re.search(r'\b' + re.escape(key) + r'\b', right_part, re.IGNORECASE):
                            return {
                                "common_name": value,
                                "cultivar_name": left_part,
                                "additional_descriptors": re.sub(r'\b' + re.escape(key) + r'\b', '', right_part, flags=re.IGNORECASE).strip() or "N/A"
                            }
    
    # Step 3: Try to identify common name and cultivar without separators
    # Look for known common names in the title
    if known_common_names:
        # Sort by length to prioritize longer matches (e.g., "Swiss Chard" over "Chard")
        sorted_common_names = sorted(known_common_names, key=len, reverse=True)
        
        for common_name in sorted_common_names:
            pattern = re.compile(r'\b' + re.escape(common_name) + r'\b', re.IGNORECASE)
            if pattern.search(processed_title):
                # Found a common name, extract the rest as potential cultivar/descriptors
                remaining = pattern.sub('', processed_title).strip()
                if remaining:
                    # If remaining text is short and has capitals, likely a cultivar
                    if len(remaining.split()) <= 4 and any(word[0].isupper() for word in remaining.split() if word):
                        return {
                            "common_name": common_name,
                            "cultivar_name": remaining,
                            "additional_descriptors": "N/A"
                        }
                    else:
                        # Otherwise, treat as descriptors
                        return {
                            "common_name": common_name,
                            "cultivar_name": "N/A",
                            "additional_descriptors": remaining if remaining else "N/A"
                        }
                else:
                    return {
                        "common_name": common_name,
                        "cultivar_name": "N/A",
                        "additional_descriptors": "N/A"
                    }
    
    # Step 4: Check COMMON_NAME_MAPPING for matches in the title
    for common_name_key, common_name_value in COMMON_NAME_MAPPING.items():
        pattern = re.compile(r'\b' + re.escape(common_name_key) + r'\b', re.IGNORECASE)
        if pattern.search(processed_title):
            # Found a common name, extract the rest as potential cultivar/descriptors
            remaining = pattern.sub('', processed_title).strip()
            
            # Handle special case for titles like "Ruby Red Lettuce"
            # where common name is at the end but should be extracted
            if remaining and common_name_key.lower() == "lettuce" and len(remaining.split()) <= 3:
                return {
                    "common_name": common_name_value,
                    "cultivar_name": remaining,
                    "additional_descriptors": "N/A"
                }
                
            if remaining:
                # Remove leading/trailing punctuation from remaining text
                remaining = remaining.strip('., -')
                
                # If remaining text is short and has capitals, likely a cultivar
                if len(remaining.split()) <= 4 and any(word[0].isupper() for word in remaining.split() if word):
                    return {
                        "common_name": common_name_value,
                        "cultivar_name": remaining,
                        "additional_descriptors": "N/A"
                    }
                else:
                    # Otherwise, treat as descriptors
                    return {
                        "common_name": common_name_value,
                        "cultivar_name": "N/A",
                        "additional_descriptors": remaining if remaining else "N/A"
                    }
            else:
                return {
                    "common_name": common_name_value,
                    "cultivar_name": "N/A",
                    "additional_descriptors": "N/A"
                }
    
    # Step 5: If we still can't find a common name, look for specific microgreen types
    # This handles cases like "Spicy Mix" or "Mild Mix"
    if re.search(r'\bmix\b', processed_title, re.IGNORECASE):
        # It's likely a mix, use the whole title as the common name
        return {
            "common_name": processed_title,
            "cultivar_name": "N/A",
            "additional_descriptors": "N/A"
        }
    
    # Step 6: If all else fails, use the first word as common name and rest as descriptors
    # This is a fallback approach
    words = processed_title.split()
    if words:
        first_word = words[0]
        rest = ' '.join(words[1:])
        
        # Check if first word is capitalized (proper noun)
        if first_word[0].isupper():
            return {
                "common_name": first_word,
                "cultivar_name": rest if rest else "N/A",
                "additional_descriptors": "N/A"
            }
        else:
            # If not capitalized, might not be a common name
            return {
                "common_name": processed_title,
                "cultivar_name": "N/A",
                "additional_descriptors": "N/A"
            }
    
    # If all else fails
    return {
        "common_name": processed_title,
        "cultivar_name": "N/A",
        "additional_descriptors": "N/A"
    }

def parse_seed_name(product_title, known_common_names=None):
    """
    Parse a product title into common name, cultivar name, and additional descriptors
    according to proper horticultural naming conventions.
    
    Args:
        product_title (str): The product title to parse
        known_common_names (list): Optional list of known common names to match against
    
    Returns:
        dict: Contains 'common_name', 'cultivar_name', and 'additional_descriptors'
    """
    result = _parse_seed_name_internal(product_title, known_common_names)
    return clean_parse_result(result)

def extract_common_name(text, known_common_names=None):
    """Extract common name from text."""
    if not text:
        return "N/A"
    
    # First try to match against known common names
    if known_common_names:
        for name in sorted(known_common_names, key=len, reverse=True):
            if re.search(r'\b' + re.escape(name) + r'\b', text, re.IGNORECASE):
                return name
    
    # Then try to match against our mapping
    for key, value in COMMON_NAME_MAPPING.items():
        if re.search(r'\b' + re.escape(key) + r'\b', text, re.IGNORECASE):
            return value
    
    # If no match, use the first word or the whole text
    words = text.split()
    if words:
        # Check if the first word looks like a common name (capitalized, not too long)
        if len(words[0]) > 1 and words[0][0].isupper() and len(words[0]) < 15:
            return words[0]
    
    # If we can't determine a specific common name
    return text

def extract_additional_descriptors(text, common_name):
    """Extract additional descriptors after removing common name."""
    if not text or not common_name or common_name == "N/A":
        return "N/A"
    
    # Remove the common name from the text
    pattern = re.compile(r'\b' + re.escape(common_name) + r'\b', re.IGNORECASE)
    remaining = pattern.sub('', text).strip()
    
    # Clean up any remaining punctuation
    remaining = remaining.strip('., -')
    
    return remaining if remaining else "N/A"

def is_common_name(text, known_common_names=None):
    """Check if text is a common name."""
    if not text:
        return False
    
    # Check against known common names
    if known_common_names:
        if text.title() in known_common_names:
            return True
    
    # Check against our mapping
    if text.lower() in COMMON_NAME_MAPPING:
        return True
    
    return False

def clean_name_component(text):
    """Clean name component by removing extra spaces, commas, and punctuation."""
    if not text or text == "N/A":
        return "N/A"
    
    # Remove trailing commas, spaces, and dashes
    cleaned = re.sub(r'^[,\-\s]+|[,\-\s]+$', '', text).strip()
    
    # Normalize internal spaces
    cleaned = ' '.join(cleaned.split())
    
    return cleaned if cleaned else "N/A"

def clean_parse_result(result):
    """Apply universal cleaning to parse result components."""
    return {
        "common_name": clean_name_component(result.get("common_name", "N/A")),
        "cultivar_name": clean_name_component(result.get("cultivar_name", "N/A")),
        "additional_descriptors": clean_name_component(result.get("additional_descriptors", "N/A"))
    }

def standardize_common_name(text):
    """Standardize common name format."""
    if not text:
        return "N/A"
    
    # Clean the text first
    text = clean_name_component(text)
    
    # Check against our mapping first
    if text.lower() in COMMON_NAME_MAPPING:
        return COMMON_NAME_MAPPING[text.lower()]
    
    # Otherwise use title case
    return text.title()

def format_seed_name(common_name, cultivar_name, additional_descriptors=None):
    """
    Format seed name components according to proper horticultural naming conventions.
    
    Args:
        common_name (str): The common name of the plant (e.g., "Lettuce")
        cultivar_name (str): The cultivar name (e.g., "Red Russian")
        additional_descriptors (str, optional): Additional descriptors (e.g., "Organic")
    
    Returns:
        str: Properly formatted seed name
    """
    if common_name == "N/A":
        return "N/A"
    
    formatted_name = common_name.title()
    
    if cultivar_name and cultivar_name != "N/A":
        # Format cultivar name with single quotes if not already
        if not (cultivar_name.startswith("'") and cultivar_name.endswith("'")):
            formatted_cultivar = f"'{cultivar_name}'"
        else:
            formatted_cultivar = cultivar_name
        
        formatted_name += f" {formatted_cultivar}"
    
    if additional_descriptors and additional_descriptors != "N/A":
        formatted_name += f" {additional_descriptors}"
    
    return formatted_name

# Example usage:
if __name__ == "__main__":
    # Example titles
    example_titles = [
        "Ruby Red Lettuce",
        "Kale, Red Russian",
        "Broccoli 'Di Cicco'",
        "Swiss Chard, Bright Lights",
        "Radish 'Daikon' - Organic",
        "4010 Green Forage Pea - Organic",
        "Greencrops, 4010 Green Forage Pea - Organic"
    ]
    
    for title in example_titles:
        parsed = parse_seed_name(title)
        print(f"Original: {title}")
        print(f"Parsed: {parsed}")
        print(f"Formatted: {format_seed_name(parsed['common_name'], parsed['cultivar_name'], parsed['additional_descriptors'])}")
        print("---") 