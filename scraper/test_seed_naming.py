#!/usr/bin/env python3
import os
import sys
from tabulate import tabulate
import logging

# Add current directory to path to import local modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_naming_utils import parse_seed_name, format_seed_name
from seed_name_parser import parse_cultivar_and_variety_from_title, parse_title_with_proper_naming, parse_with_botanical_field_names

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def print_header(text):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80)

def test_examples():
    """Test seed naming utilities with example product titles."""
    print_header("SEED NAMING EXAMPLES")
    
    example_titles = [
        "Ruby Red Lettuce",
        "Kale, Red Russian",
        "Broccoli 'Di Cicco'",
        "Swiss Chard, Bright Lights",
        "Radish 'Daikon' - Organic",
        "4010 Green Forage Pea - Organic",
        "Sunflower, Black Oil",
        "Spicy Mix",
        "Beet, Bull's Blood",
        "Lettuce Mix, Organic",
        "Wheatgrass",
        "Nasturtium, Organic",
        "Mesclun Mix - Lettuce",
        "Greencrops, 4010 Green Forage Pea - Organic"
    ]
    
    results = []
    
    for title in example_titles:
        # Parse with the new utility
        parsed = parse_title_with_proper_naming(title)
        common_name = parsed['common_name']
        cultivar_name = parsed['cultivar_name']
        additional_descriptors = parsed['additional_descriptors']
        
        # Format properly
        formatted = format_seed_name(common_name, cultivar_name, additional_descriptors)
        
        # Also get the backward compatible version
        compat = parse_cultivar_and_variety_from_title(title)
        
        results.append([
            title,
            common_name,
            cultivar_name,
            additional_descriptors,
            formatted,
            compat['cultivar'],
            compat['plant_variety']
        ])
    
    headers = [
        "Original Title", 
        "Common Name", 
        "Cultivar Name", 
        "Additional Descriptors",
        "Properly Formatted",
        "Legacy 'common_name' field", 
        "Legacy 'cultivar_name' field"
    ]
    
    print(tabulate(results, headers=headers, tablefmt="grid"))

def test_challenging_examples():
    """Test seed naming utilities with challenging product titles."""
    print_header("CHALLENGING EXAMPLES")
    
    challenging_titles = [
        "USDA Certified Organic Sunflower Black Oil Seed",
        "Certified Organic Superfood Sprouting Seed Mix - 1 lb Bag",
        "Organic 'Daikon' Radish Seeds",
        "Bright Lights Beta Mix",
        "Green Peas (USA)",
        "Mung Bean Sprouting Seeds - Certified Organic",
        "Red Bull's Blood Beet",
        "Rainbow Mix - 5 Types of Microgreens",
        "4010 Forage Pea Seeds",
        "Buckwheat Seeds for Microgreens (Non-GMO)",
        "Organic Mild Mix (Sunflower, Pea, Radish)",
        "Greencrops, 4010 Green Forage Pea - Organic"
    ]
    
    results = []
    
    for title in challenging_titles:
        # Parse with the new utility
        parsed = parse_title_with_proper_naming(title)
        common_name = parsed['common_name']
        cultivar_name = parsed['cultivar_name']
        additional_descriptors = parsed['additional_descriptors']
        
        # Format properly
        formatted = format_seed_name(common_name, cultivar_name, additional_descriptors)
        
        results.append([
            title,
            common_name,
            cultivar_name,
            additional_descriptors,
            formatted
        ])
    
    headers = [
        "Original Title", 
        "Common Name", 
        "Cultivar Name", 
        "Additional Descriptors",
        "Properly Formatted"
    ]
    
    print(tabulate(results, headers=headers, tablefmt="grid"))

def test_real_data():
    """Test seed naming utilities with real data from our scrapers."""
    print_header("REAL DATA EXAMPLES FROM SCRAPERS")
    
    real_examples = [
        "Swiss Chard, Ruby Red",
        "Greencrops, 4010 Green Forage Pea - Organic",
        "Swiss Chard, Eldorado",
        "Amish Deer Tongue Lettuce",
        "Alfalfa, Common - Organic",
        "Arugula, Wasabi",
        "Basil, Red Rubin",
        "Dwarf Siberian Kale",
        "Swiss Chard, Rainbow",
        "Pea, 4010 Forage - Organic"
    ]
    
    results = []
    
    for title in real_examples:
        # Parse with the new utility
        parsed = parse_title_with_proper_naming(title)
        common_name = parsed['common_name']
        cultivar_name = parsed['cultivar_name']
        additional_descriptors = parsed['additional_descriptors']
        
        # Format properly
        formatted = format_seed_name(common_name, cultivar_name, additional_descriptors)
        
        # Also get the backward compatible version
        compat = parse_cultivar_and_variety_from_title(title)
        
        results.append([
            title,
            formatted,
            compat['cultivar'],
            compat['plant_variety']
        ])
    
    headers = [
        "Original Title", 
        "Properly Formatted",
        "Legacy 'common_name' field",
        "Legacy 'cultivar_name' field"
    ]
    
    print(tabulate(results, headers=headers, tablefmt="grid"))

def compare_parsing_methods():
    """Compare different parsing methods on the problematic example."""
    print_header("COMPARING PARSING METHODS ON PROBLEMATIC EXAMPLE")
    
    problematic_example = "Greencrops, 4010 Green Forage Pea - Organic"
    
    # Old method
    old_result = parse_cultivar_and_variety_from_title(problematic_example)
    
    # New method
    new_result = parse_title_with_proper_naming(problematic_example)
    
    # Direct parsing method
    direct_result = parse_seed_name(problematic_example)
    
    print(f"Original title: {problematic_example}\n")
    
    print("1. Old parsing method (backward compatible):")
    print(f"   common_name: {old_result['cultivar']}")
    print(f"   cultivar_name: {old_result['plant_variety']}\n")
    
    print("2. New parsing method:")
    print(f"   common_name: {new_result['common_name']}")
    print(f"   cultivar_name: {new_result['cultivar_name']}")
    print(f"   additional_descriptors: {new_result['additional_descriptors']}\n")
    
    print("3. Direct parsing method:")
    print(f"   common_name: {direct_result['common_name']}")
    print(f"   cultivar_name: {direct_result['cultivar_name']}")
    print(f"   additional_descriptors: {direct_result['additional_descriptors']}")
    
    formatted = format_seed_name(
        new_result['common_name'],
        new_result['cultivar_name'],
        new_result['additional_descriptors']
    )
    
    print(f"\nProperly formatted: {formatted}")

if __name__ == "__main__":
    test_examples()
    test_challenging_examples()
    test_real_data()
    compare_parsing_methods() 