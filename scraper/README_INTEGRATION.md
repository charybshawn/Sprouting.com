# Integrating Proper Seed Naming into Scrapers

This document provides step-by-step instructions for integrating the new seed naming utilities into the existing scrapers.

## Background

We've implemented a proper horticultural naming convention for seed varieties that separates:
- **Common Name**: The everyday name of the plant (e.g., "Lettuce")
- **Cultivar Name**: The specific cultivar in single quotes (e.g., 'Red Russian')
- **Additional Descriptors**: Extra information like "Organic"

Our previous approach incorrectly labeled common names as "cultivars" and cultivar names as "plant_variety".

## Integration Options

### Option 1: Backward Compatible Integration

This approach maintains the existing JSON structure but uses the new utilities to correctly identify common names and cultivars.

#### Step 1: Replace the parsing function

In each scraper file, replace the existing `parse_cultivar_and_variety_from_title` function with an import from the new utility:

```python
# Replace this line:
from seed_name_parser import parse_cultivar_and_variety_from_title

# Then remove your existing parse_cultivar_and_variety_from_title function
```

The new function has the same signature and return structure but follows proper naming conventions.

#### Step 2: Test the changes

Run your scraper with a small sample to ensure it still works as expected:

```bash
python scraper/sprouting_scraper.py --test
```

### Option 2: Full Integration with Enhanced JSON Output

This approach updates the JSON output format to include all seed naming components.

#### Step 1: Update the JSON output structure

In your main scraping function or where you build the product objects, update the structure to include all components:

```python
from seed_name_parser import parse_title_with_proper_naming, format_properly

# Get both backward compatible and new fields
parsed_backward = parse_cultivar_and_variety_from_title(title)
parsed_full = parse_title_with_proper_naming(title)

product_data = {
    'title': title,
    # Backward compatibility fields (old naming but correctly parsed)
    'cultivar': parsed_backward['cultivar'],
    'plant_variety': parsed_backward['plant_variety'],
    # New fields with proper naming
    'common_name': parsed_full['common_name'],
    'cultivar_name': parsed_full['cultivar_name'],
    'additional_descriptors': parsed_full['additional_descriptors'],
    'formatted_name': format_properly(
        parsed_full['common_name'], 
        parsed_full['cultivar_name'], 
        parsed_full['additional_descriptors']
    ),
    # Other fields...
}
```

#### Step 2: Update JSON schema documentation

Update your JSON schema documentation to reflect the new fields.

### Option 3: Generate Common Names and Cultivars CSVs

For improved parsing accuracy, periodically regenerate the common names and cultivars CSV files.

```bash
python scraper/create_common_names_csv.py
```

This will:
1. Create/update `scraper_data/common_names.csv` with a list of common plant names
2. Create/update `scraper_data/cultivars.csv` with cultivars organized by common name

## Implementation Examples

### Example 1: Minimal change in sprouting_scraper.py

```python
# At the top of the file, add:
from seed_name_parser import parse_cultivar_and_variety_from_title

# Remove your existing parse_cultivar_and_variety_from_title function
```

### Example 2: Full implementation in sprouting_scraper.py

```python
# At the top of the file, add:
from seed_name_parser import parse_cultivar_and_variety_from_title, parse_title_with_proper_naming, format_properly

# In your scrape_product_details function, update the product data structure:
def scrape_product_details(page, product_url):
    # ... existing code ...
    
    # Parse the title with both methods
    parsed_backward = parse_cultivar_and_variety_from_title(title)
    parsed_full = parse_title_with_proper_naming(title)
    
    product_data = {
        'title': title,
        # Backward compatibility fields
        'cultivar': parsed_backward['cultivar'],
        'plant_variety': parsed_backward['plant_variety'],
        # New fields with proper naming
        'common_name': parsed_full['common_name'],
        'cultivar_name': parsed_full['cultivar_name'],
        'additional_descriptors': parsed_full['additional_descriptors'],
        'formatted_name': format_properly(
            parsed_full['common_name'], 
            parsed_full['cultivar_name'], 
            parsed_full['additional_descriptors']
        ),
        # Other existing fields...
    }
    
    # ... rest of the function ...
```

## Testing Your Integration

After integrating the new utilities, run the test script to see how your product titles will be parsed:

```bash
python scraper/test_seed_naming.py
```

Add your own examples to the script to test specific product titles from your scrapers.

## Common Issues and Solutions

### 1. Dependency Errors

If you see import errors, make sure the utilities are in the correct directory and that the directory is in your Python path.

### 2. Parsing Ambiguities

Some product titles might be parsed differently than expected. Add specific cases to the COMMON_NAME_MAPPING dictionary in seed_naming_utils.py.

### 3. Performance Concerns

The new utilities do more processing than the old function. If performance is an issue, consider caching parsed results or preprocessing titles.

## Next Steps

1. Run the `create_common_names_csv.py` script to generate initial CSV files
2. Integrate the utilities into your scrapers using one of the options above
3. Test with a small sample to ensure everything works as expected
4. Update any downstream code that processes the scraped data 