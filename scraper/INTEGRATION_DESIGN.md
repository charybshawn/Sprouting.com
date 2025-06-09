# Seed Scraper Data Integration Design Document

## Overview

This document outlines the design specifications for programs that import and utilize JSON data from the microgreen seed scrapers. The scrapers collect product information from multiple Canadian and international suppliers, providing standardized data for pricing analysis, inventory management, and purchasing decisions.

## Data Sources

### Supported Suppliers
- **sprouting.com** (Canadian, CAD, tax-exempt)
- **germina.ca** (Canadian, CAD, tax-exempt) 
- **damseeds.com** (Canadian, CAD, tax-exempt)
- **johnnyseeds.com** (US, USD, taxable imports)

### File Locations
```
scraper_data/json_files/
├── mumms_seeds/          # sprouting.com data
├── germina_seeds/        # germina.ca data  
├── damm_seeds/          # damseeds.com data
└── johnny_seeds/        # johnnyseeds.com data
```

## JSON Schema Specification

### Root Object Structure
```json
{
  "timestamp": "2025-06-05T23:21:27.732082",
  "scrape_duration_seconds": 5.46,
  "source_site": "https://johnnyseeds.com",
  "currency_code": "USD",
  "product_count": 1,
  "data": [/* Array of product objects */]
}
```

### Product Object Schema
```json
{
  "title": "Mustard, Red Katana",
  "url": "https://www.johnnyseeds.com/...",
  "common_name": "Mustard",
  "cultivar_name": "Red Katana", 
  "organic": false,
  "is_in_stock": true,
  "variations": [/* Array of variation objects */]
}
```

### Variation Object Schema
```json
{
  "size": "1 ounce",
  "price": 10.9,
  "is_variation_in_stock": true,
  "weight_kg": 0.0283495,
  "original_weight_value": 1.0,
  "original_weight_unit": "oz",
  "sku": "5515MG.32",
  "canadian_costs": {
    "base_price_cad": 14.93,
    "shipping_cad": 17.12,
    "duties_cad": 0.0,
    "taxes_cad": 1.79,
    "brokerage_cad": 17.5,
    "total_cad": 51.35,
    "markup_percentage": 243.9
  }
}
```

## Integration Patterns

### 1. Price Comparison Engine

**Purpose**: Compare prices across suppliers for equivalent products

**Key Features**:
- Normalize weights to common units (kg)
- Calculate per-kg pricing including all costs
- Account for shipping sweet spots (10kg+ orders)
- Filter by organic/conventional preferences

**Implementation Example**:
```python
class PriceComparisonEngine:
    def __init__(self):
        self.suppliers = self.load_all_supplier_data()
    
    def find_best_price(self, common_name: str, min_weight_kg: float = 0.1) -> List[PriceOption]:
        """Find best prices for a seed type across all suppliers"""
        matches = []
        for supplier_data in self.suppliers:
            for product in supplier_data['data']:
                if product['common_name'].lower() == common_name.lower():
                    for variation in product['variations']:
                        if variation['weight_kg'] >= min_weight_kg:
                            price_per_kg = variation['canadian_costs']['total_cad'] / variation['weight_kg']
                            matches.append(PriceOption(
                                supplier=supplier_data['source_site'],
                                product=product,
                                variation=variation,
                                price_per_kg=price_per_kg
                            ))
        return sorted(matches, key=lambda x: x.price_per_kg)
```

### 2. Inventory Management System

**Purpose**: Track available products and optimal order quantities

**Key Features**:
- Monitor stock status across suppliers
- Calculate optimal order sizes (shipping sweet spots)
- Generate purchase recommendations
- Track price history over time

**Database Schema**:
```sql
-- Products table
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    common_name VARCHAR(100),
    cultivar_name VARCHAR(100),
    organic BOOLEAN,
    supplier_url VARCHAR(255),
    last_updated TIMESTAMP
);

-- Variations table  
CREATE TABLE variations (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id),
    size_description VARCHAR(100),
    weight_kg DECIMAL(10,6),
    price_source_currency DECIMAL(10,2),
    total_price_cad DECIMAL(10,2),
    is_in_stock BOOLEAN,
    sku VARCHAR(100),
    last_updated TIMESTAMP
);

-- Price history table
CREATE TABLE price_history (
    id SERIAL PRIMARY KEY,
    variation_id INTEGER REFERENCES variations(id),
    price_cad DECIMAL(10,2),
    in_stock BOOLEAN,
    recorded_at TIMESTAMP
);
```

### 3. Order Optimization Calculator

**Purpose**: Determine optimal order combinations to minimize total costs

**Key Features**:
- Mix products from single supplier to reach shipping sweet spots
- Calculate total order costs including shipping economies
- Suggest order timing based on stock availability
- Generate shopping lists with cost projections

**Algorithm Example**:
```python
class OrderOptimizer:
    def optimize_order(self, required_seeds: List[SeedRequirement]) -> OrderPlan:
        """
        Optimize order to minimize costs while meeting requirements
        
        Args:
            required_seeds: List of (common_name, min_weight_kg, max_price_per_kg)
            
        Returns:
            OrderPlan with supplier groupings and total costs
        """
        # Group by supplier to leverage shipping economies
        supplier_groups = self.group_by_supplier(required_seeds)
        
        # For each supplier, calculate optimal quantities
        optimized_orders = []
        for supplier, seed_list in supplier_groups.items():
            # Try to reach 10kg+ for optimal shipping rates
            order = self.optimize_supplier_order(supplier, seed_list, target_weight=10.0)
            optimized_orders.append(order)
            
        return OrderPlan(orders=optimized_orders)
    
    def calculate_shipping_savings(self, weight_kg: float) -> float:
        """Calculate shipping cost based on Canada Post rates"""
        if weight_kg <= 2:
            return weight_kg * 12.90
        elif weight_kg <= 5:
            return weight_kg * 7.02
        elif weight_kg <= 15:
            return weight_kg * 4.15  # Sweet spot!
        elif weight_kg <= 35:
            return weight_kg * 2.90
        else:
            return weight_kg * 2.34
```

### 4. Market Analysis Dashboard

**Purpose**: Provide insights into seed market trends and opportunities

**Key Features**:
- Price trend analysis over time
- Stock availability monitoring
- Supplier comparison metrics
- Cost advantage analysis (Canadian vs international)

**Metrics to Track**:
```python
class MarketAnalytics:
    def calculate_metrics(self, time_period: str = '30d') -> Dict:
        return {
            'average_price_per_kg_by_type': self.get_avg_prices_by_seed_type(),
            'stock_availability_rate': self.calculate_availability_rates(),
            'price_volatility': self.calculate_price_changes(time_period),
            'supplier_cost_advantage': self.compare_supplier_costs(),
            'shipping_optimization_savings': self.analyze_shipping_patterns()
        }
    
    def identify_opportunities(self) -> List[Opportunity]:
        """Identify market opportunities"""
        opportunities = []
        
        # Find products with significant price differences between suppliers
        price_gaps = self.find_price_arbitrage_opportunities()
        
        # Identify products frequently out of stock (supply constraints)
        supply_issues = self.find_supply_constrained_products()
        
        # Find optimal purchase timing based on price trends
        timing_opportunities = self.analyze_seasonal_patterns()
        
        return opportunities
```

## Integration Considerations

### Data Freshness
- **Update Frequency**: Data should be refreshed every 24-48 hours
- **Staleness Detection**: Flag data older than 7 days as potentially stale
- **Change Detection**: Monitor for significant price or availability changes

### Error Handling
```python
class DataIntegrityChecker:
    def validate_json_file(self, filepath: str) -> ValidationResult:
        """Validate JSON file structure and data quality"""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Check required fields
            required_fields = ['timestamp', 'source_site', 'currency_code', 'data']
            for field in required_fields:
                if field not in data:
                    return ValidationResult(valid=False, error=f"Missing field: {field}")
            
            # Validate product data
            for product in data['data']:
                if not self.validate_product(product):
                    return ValidationResult(valid=False, error=f"Invalid product: {product.get('title')}")
            
            return ValidationResult(valid=True)
        except Exception as e:
            return ValidationResult(valid=False, error=str(e))
```

### Currency Handling
```python
class CurrencyConverter:
    def __init__(self):
        self.exchange_rates = {
            'USD_TO_CAD': 1.37,  # Update regularly
            'CAD_TO_CAD': 1.0
        }
    
    def normalize_to_cad(self, price: float, currency: str) -> float:
        """Convert all prices to CAD for comparison"""
        rate_key = f"{currency}_TO_CAD"
        return price * self.exchange_rates.get(rate_key, 1.0)
```

### Performance Optimization
- **Indexing**: Index products by common_name, supplier, and in_stock status
- **Caching**: Cache frequently accessed price comparisons
- **Batch Processing**: Process multiple JSON files concurrently
- **Incremental Updates**: Only process changed data when possible

## API Design Patterns

### RESTful API Example
```python
# GET /api/v1/products?common_name=arugula&in_stock=true
# GET /api/v1/suppliers/{supplier_id}/products
# GET /api/v1/price-comparison?seeds=arugula,mustard&min_weight=0.5
# POST /api/v1/orders/optimize
```

### Response Format
```json
{
  "status": "success",
  "data": {
    "products": [...],
    "pagination": {
      "page": 1,
      "per_page": 50,
      "total": 150
    }
  },
  "meta": {
    "last_updated": "2025-06-05T23:21:27Z",
    "data_freshness": "24h"
  }
}
```

## Security Considerations

- **Rate Limiting**: Prevent abuse of supplier websites through scraper overuse
- **Data Privacy**: Ensure supplier pricing data is used ethically
- **Access Control**: Limit access to pricing data to authorized users
- **Audit Trail**: Log all data access and modifications

## Deployment Architecture

### Recommended Stack
- **Database**: PostgreSQL with JSON support
- **Cache**: Redis for frequently accessed data
- **API**: FastAPI or Django REST Framework
- **Frontend**: React/Vue.js for dashboards
- **Monitoring**: Prometheus + Grafana for data freshness tracking

### Scalability Considerations
- Horizontal scaling for API servers
- Database read replicas for heavy read workloads
- CDN for static dashboard assets
- Message queues for batch processing tasks

This design provides a solid foundation for building applications that leverage the seed scraper data effectively while maintaining performance, reliability, and data integrity.