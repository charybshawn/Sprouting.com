#!/usr/bin/env python3
import os
import sys
from tabulate import tabulate

# Add current directory to path to import local modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import both parsers
from simplified_seed_parser import parse_seed_title as simplified_parse
from seed_name_parser import parse_with_proper_naming as complex_parse

def compare_parsers():
    """Compare the simplified parser with the complex parser."""
    print("\n" + "=" * 80)
    print("  COMPARING SIMPLIFIED PARSER WITH COMPLEX PARSER")
    print("=" * 80)
    
    test_titles = [
        "Ruby Red Lettuce",
        "Kale, Red Russian",
        "Broccoli 'Di Cicco'",
        "Swiss Chard, Bright Lights",
        "Radish 'Daikon' - Organic",
        "4010 Green Forage Pea - Organic",
        "Greencrops, 4010 Green Forage Pea - Organic",
        "USDA Certified Organic Sunflower Black Oil Seed",
        "Spicy Mix Microgreens",
        "Mung Bean Sprouting Seeds",
        "Bull's Blood Beet",
        "Dwarf Siberian Kale"
    ]
    
    results = []
    
    for title in test_titles:
        # Parse with simplified parser
        simple_result = simplified_parse(title)
        
        # Parse with complex parser
        complex_result = complex_parse(title)
        
        # Compare results
        simple_common = simple_result["common_name"]
        simple_cultivar = simple_result["cultivar_name"]
        complex_common = complex_result["common_name"]
        complex_cultivar = complex_result["cultivar_name"]
        complex_desc = complex_result["additional_descriptors"]
        
        # Check if results match
        common_match = simple_common == complex_common
        cultivar_match = simple_cultivar == complex_cultivar
        overall_match = common_match and cultivar_match
        
        results.append([
            title,
            simple_common,
            simple_cultivar,
            complex_common,
            complex_cultivar,
            complex_desc,
            "✓" if common_match else "✗",
            "✓" if cultivar_match else "✗",
            "✓" if overall_match else "✗"
        ])
    
    # Calculate match percentages
    total = len(results)
    common_matches = sum(1 for r in results if r[6] == "✓")
    cultivar_matches = sum(1 for r in results if r[7] == "✓")
    overall_matches = sum(1 for r in results if r[8] == "✓")
    
    common_pct = (common_matches / total) * 100
    cultivar_pct = (cultivar_matches / total) * 100
    overall_pct = (overall_matches / total) * 100
    
    # Print comparison table
    headers = [
        "Title",
        "Simple Common",
        "Simple Cultivar",
        "Complex Common",
        "Complex Cultivar",
        "Complex Desc",
        "Common Match",
        "Cultivar Match",
        "Overall Match"
    ]
    
    print(tabulate(results, headers=headers, tablefmt="grid"))
    
    # Print match statistics
    print("\nMATCH STATISTICS:")
    print(f"Common Name Matches: {common_matches}/{total} ({common_pct:.1f}%)")
    print(f"Cultivar Name Matches: {cultivar_matches}/{total} ({cultivar_pct:.1f}%)")
    print(f"Overall Matches: {overall_matches}/{total} ({overall_pct:.1f}%)")
    
    # Print differences
    print("\nDIFFERENCES:")
    differences = [(i, r) for i, r in enumerate(results) if r[8] == "✗"]
    for idx, row in differences:
        title = row[0]
        print(f"{idx+1}. \"{title}\":")
        print(f"   Simplified: {row[1]} / {row[2]}")
        print(f"   Complex:    {row[3]} / {row[4]} / {row[5]}")
        print()

if __name__ == "__main__":
    compare_parsers() 