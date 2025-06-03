# Proper Seed Naming Conventions

This document explains the proper naming conventions for seeds based on horticultural standards, and how to use the new utility files for consistent seed naming across our scrapers.

## Seed Naming Structure

According to proper horticultural naming conventions, seed varieties should be identified using the following components:

1. **Common Name**: The everyday name of the plant, such as "Lettuce," "Radish," or "Kale." This is the starting point for gardeners to identify the type of vegetable or microgreen.

2. **Cultivar Name**: A cultivar (short for "cultivated variety") is a plant selected or bred for specific traits. Cultivar names should be enclosed in single quotes and capitalized. For example, 'Daikon' is a cultivar of Radish.

3. **Additional Descriptors**: These might include trade designations, descriptive terms like "Organic" or "Heirloom," or other marketing-related terms.

## Correct Formatting Examples

| Original Product Title | Properly Formatted Name |
|------------------------|-------------------------|
| "Ruby Red Lettuce" | Lettuce 'Ruby Red' |
| "Kale, Red Russian" | Kale 'Red Russian' |
| "Broccoli 'Di Cicco'" | Broccoli 'Di Cicco' |
| "Swiss Chard, Bright Lights" | Swiss Chard 'Bright Lights' |
| "Radish 'Daikon' - Organic" | Radish 'Daikon' Organic |

## Previous Approach vs New Approach

Our previous approach mixed up the concepts of cultivars and common names:

- We were treating common names as "cultivars" in our data structure
- What we called "plant_variety" was sometimes the cultivar name, sometimes additional descriptors

The new approach aligns with proper horticultural naming conventions:

- `common_name`: The everyday name of the plant (e.g., "Lettuce")
- `cultivar_name`: The specific cultivar in single quotes (e.g., 'Red Russian')
- `additional_descriptors`: Additional terms like "Organic" or descriptive attributes

## How to Use the New Utilities

### 1. For New Code

Use the `seed_naming_utils.py` module directly:

```python
from seed_naming_utils import parse_seed_name, format_seed_name

# Parse a product title
parsed = parse_seed_name("Ruby Red Lettuce")
print(parsed)
# Output: {'common_name': 'Lettuce', 'cultivar_name': 'Ruby Red', 'additional_descriptors': 'N/A'}

# Format a seed name properly
formatted = format_seed_name('Lettuce', 'Ruby Red')
print(formatted)
# Output: "Lettuce 'Ruby Red'"
```

### 2. For Backward Compatibility with Existing Scrapers

Use the `seed_name_parser.py` module, which provides a drop-in replacement for the old `parse_cultivar_and_variety_from_title` function:

```python
from seed_name_parser import parse_cultivar_and_variety_from_title

# This returns the same structure as the old function, but with proper naming conventions applied
result = parse_cultivar_and_variety_from_title("Ruby Red Lettuce")
print(result)
# Output: {'cultivar': 'Lettuce', 'plant_variety': 'Ruby Red'}
```

For full parsing with all three components:

```python
from seed_name_parser import parse_title_with_proper_naming

result = parse_title_with_proper_naming("Ruby Red Lettuce")
print(result)
# Output: {'common_name': 'Lettuce', 'cultivar_name': 'Ruby Red', 'additional_descriptors': 'N/A'}
```

### 3. Generating the Common Names and Cultivars CSVs

Run the `create_common_names_csv.py` script to generate two CSV files:

1. `common_names.csv`: Contains a list of common plant names
2. `cultivars.csv`: Contains cultivars organized by common name

```bash
python scraper/create_common_names_csv.py
```

## JSON Output Format

The JSON output format has been updated to include all three components:

```json
{
  "data": [
    {
      "title": "Ruby Red Lettuce",
      "common_name": "Lettuce",
      "cultivar_name": "Ruby Red",
      "additional_descriptors": "",
      "formatted_name": "Lettuce 'Ruby Red'",
      // backward compatibility fields
      "cultivar": "Lettuce",
      "plant_variety": "Ruby Red",
      // other fields...
    }
  ]
}
```

## Why This Matters

Proper seed naming is important for:

1. **Accuracy**: Ensuring that seeds are identified consistently and correctly.
2. **Searchability**: Enabling users to find seeds based on common names or cultivars.
3. **Consistency**: Providing a standard naming convention across all our data sources.
4. **Horticultural Standards**: Aligning with accepted naming conventions in the gardening and agricultural communities.

## References

For more information on horticultural naming conventions, see:

- [American Seed Trade Association guidelines](https://www.betterseed.org/)
- [International Code of Nomenclature for Cultivated Plants](https://www.ishs.org/scripta-horticulturae/international-code-nomenclature-cultivated-plants-ninth-edition) 