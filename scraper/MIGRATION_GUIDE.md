# Seed Naming Migration Guide

This guide explains how to update all scrapers to use the new field naming convention for seed varieties.

## Field Naming Changes

We're changing the field names to match proper horticultural naming conventions:

| Old Field Name | New Field Name | Description |
|---------------|----------------|-------------|
| `cultivar` | `common_name` | The everyday name of the plant (e.g., "Lettuce") |
| `plant_variety` | `cultivar_name` | The specific cultivar name (e.g., "Red Russian") |
| N/A | `additional_descriptors` | Extra descriptive information (e.g., "Organic") |
| N/A | `formatted_name` | Properly formatted full name (e.g., "Lettuce 'Red Russian' Organic") |

## Migration Options

### Option 1: Immediate Full Migration

Replace all occurrences of the old field names with the new ones across all scrapers.

### Option 2: Gradual Migration with Backward Compatibility

Add the new fields while keeping the old ones for backward compatibility.

## Step-by-Step Migration

### 1. Update JSON Output Structure

Update the product data structure in each scraper:

```python
from seed_name_parser import parse_with_proper_naming

# Get parsed seed name
parsed = parse_with_proper_naming(title)

product_data = {
    'title': title,
    # New field names
    'common_name': parsed['common_name'],
    'cultivar_name': parsed['cultivar_name'],
    'additional_descriptors': parsed['additional_descriptors'],
    # For backward compatibility (optional)
    'cultivar': parsed['common_name'],
    'plant_variety': parsed['cultivar_name'],
    # Other fields...
}
```

### 2. Update Scraper Files

The following files need to be updated:

- `sprouting_scraper.py`
- `germina_scraper.py`
- `damseeds_scraper.py`

For each file:

1. Import the new parser function:
   ```python
   from seed_name_parser import parse_with_proper_naming
   ```

2. Replace the old parsing logic with the new one:
   ```python
   # Replace this:
   parsed_title_info = parse_cultivar_and_variety_from_title(title)
   product_data['cultivar'] = parsed_title_info['cultivar']
   product_data['plant_variety'] = parsed_title_info['plant_variety']
   
   # With this:
   parsed = parse_with_proper_naming(title)
   product_data['common_name'] = parsed['common_name']
   product_data['cultivar_name'] = parsed['cultivar_name']
   product_data['additional_descriptors'] = parsed['additional_descriptors']
   # For backward compatibility (optional):
   product_data['cultivar'] = parsed['common_name']
   product_data['plant_variety'] = parsed['cultivar_name']
   ```

### 3. Update JSON Schema Documentation

Update any documentation that describes the JSON output format:

```json
{
  "data": [
    {
      "title": "Ruby Red Lettuce",
      "common_name": "Lettuce",
      "cultivar_name": "Ruby Red",
      "additional_descriptors": "",
      "formatted_name": "Lettuce 'Ruby Red'",
      // Legacy fields (optional, for backward compatibility)
      "cultivar": "Lettuce",
      "plant_variety": "Ruby Red",
      // Other fields...
    }
  ]
}
```

### 4. Handle Problematic Cases

For titles like "Greencrops, 4010 Green Forage Pea - Organic", the new parser will correctly identify:
- `common_name`: "Pea"
- `cultivar_name`: "Greencrops"
- `additional_descriptors`: Relevant parts

No special handling is needed for these cases anymore, as the improved parser correctly handles them.

### 5. Generate Updated CSV Files

Run the new CSV generator to update the common names and cultivars lists:

```bash
python scraper/create_common_names_csv.py
```

This will create/update:
- `scraper_data/common_names.csv`: List of common plant names
- `scraper_data/cultivars.csv`: Cultivars organized by common name

### 6. Update Downstream Code

If any downstream code or applications rely on the old field names, update them to use the new field names.

## Testing

After migration, verify the changes:

1. Run each scraper with a small test sample:
   ```bash
   python scraper/sprouting_scraper.py --test
   ```

2. Examine the output JSON to ensure the new fields are populated correctly.

3. Run the test script to verify parsing of various title formats:
   ```bash
   python scraper/test_seed_naming.py
   ```

## Migration Status Tracking

Track the migration status for each component:

| Component | Status | Notes |
|-----------|--------|-------|
| seed_naming_utils.py | Complete | New implementation with proper naming |
| seed_name_parser.py | Complete | Updated with backward compatibility |
| create_common_names_csv.py | Complete | New implementation |
| sprouting_scraper.py | Pending | |
| germina_scraper.py | Pending | |
| damseeds_scraper.py | Pending | |
| Documentation | In Progress | | 