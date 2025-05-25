#!/usr/bin/env python3
import pandas as pd
import matplotlib.pyplot as plt
import os
import sys

def load_data(filename="sprouting_products.csv"):
    """Load the scraped product data from CSV file"""
    if not os.path.exists(filename):
        print(f"Error: File {filename} not found.")
        sys.exit(1)
        
    return pd.read_csv(filename)

def clean_price_data(df):
    """Convert price columns to numeric values"""
    price_columns = ['price_75g', 'price_150g', 'price_1kg', 'price_5kg', 'price_10kg']
    
    for col in price_columns:
        if col in df.columns:
            # Remove currency symbols and convert to float
            df[col] = df[col].str.replace('$', '').str.replace(',', '').astype(float)
    
    return df

def calculate_price_per_gram(df):
    """Calculate price per gram for each quantity option"""
    if 'price_75g' in df.columns:
        df['price_per_gram_75g'] = df['price_75g'] / 75
    
    if 'price_150g' in df.columns:
        df['price_per_gram_150g'] = df['price_150g'] / 150
    
    if 'price_1kg' in df.columns:
        df['price_per_gram_1kg'] = df['price_1kg'] / 1000
    
    if 'price_5kg' in df.columns:
        df['price_per_gram_5kg'] = df['price_5kg'] / 5000
    
    if 'price_10kg' in df.columns:
        df['price_per_gram_10kg'] = df['price_10kg'] / 10000
    
    return df

def analyze_pricing(df):
    """Analyze pricing patterns"""
    print("\n=== PRICE ANALYSIS ===")
    
    # Calculate average prices by quantity
    price_columns = ['price_75g', 'price_150g', 'price_1kg', 'price_5kg', 'price_10kg']
    for col in price_columns:
        if col in df.columns:
            avg_price = df[col].mean()
            print(f"Average {col}: ${avg_price:.2f}")
    
    # Calculate average price per gram
    price_per_gram_cols = [col for col in df.columns if 'price_per_gram' in col]
    for col in price_per_gram_cols:
        if col in df.columns:
            avg_price_per_gram = df[col].mean()
            print(f"Average {col}: ${avg_price_per_gram:.5f}")
    
    # Calculate bulk discounts
    if all(col in df.columns for col in ['price_per_gram_75g', 'price_per_gram_1kg']):
        avg_discount = ((df['price_per_gram_75g'] - df['price_per_gram_1kg']) / df['price_per_gram_75g']) * 100
        print(f"Average discount from 75g to 1kg: {avg_discount.mean():.2f}%")
    
    if all(col in df.columns for col in ['price_per_gram_1kg', 'price_per_gram_10kg']):
        avg_discount = ((df['price_per_gram_1kg'] - df['price_per_gram_10kg']) / df['price_per_gram_1kg']) * 100
        print(f"Average discount from 1kg to 10kg: {avg_discount.mean():.2f}%")

def visualize_data(df):
    """Create visualizations for the pricing data"""
    # Create output directory for plots
    os.makedirs("plots", exist_ok=True)
    
    # Boxplot of prices for each quantity
    price_columns = [col for col in df.columns if col.startswith('price_') and not col.startswith('price_per_gram')]
    if price_columns:
        plt.figure(figsize=(12, 6))
        df[price_columns].boxplot()
        plt.title('Price Distribution by Quantity')
        plt.ylabel('Price ($)')
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig('plots/price_distribution.png')
        print("Saved price distribution plot to plots/price_distribution.png")
    
    # Barplot of average price per gram
    price_per_gram_cols = [col for col in df.columns if 'price_per_gram' in col]
    if price_per_gram_cols:
        plt.figure(figsize=(12, 6))
        avg_prices = df[price_per_gram_cols].mean()
        avg_prices.plot(kind='bar')
        plt.title('Average Price per Gram by Quantity')
        plt.ylabel('Price per Gram ($)')
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig('plots/avg_price_per_gram.png')
        print("Saved average price per gram plot to plots/avg_price_per_gram.png")
    
    # Scatter plot comparing 75g price vs 1kg price
    if all(col in df.columns for col in ['price_75g', 'price_1kg']):
        plt.figure(figsize=(10, 8))
        plt.scatter(df['price_75g'], df['price_1kg'])
        plt.title('75g Price vs 1kg Price')
        plt.xlabel('75g Price ($)')
        plt.ylabel('1kg Price ($)')
        plt.grid(True, alpha=0.3)
        
        # Add product names as annotations
        for i, txt in enumerate(df['name']):
            plt.annotate(txt, (df['price_75g'].iloc[i], df['price_1kg'].iloc[i]), 
                         fontsize=8, alpha=0.7)
        
        plt.tight_layout()
        plt.savefig('plots/price_comparison.png')
        print("Saved price comparison plot to plots/price_comparison.png")

def main():
    print("=== SPROUTING.COM PRODUCT ANALYSIS ===")
    
    # Load the data
    df = load_data()
    print(f"Loaded {len(df)} products")
    
    # Basic stats
    print("\n=== PRODUCT SUMMARY ===")
    print(f"Number of products: {len(df)}")
    
    # Clean and prepare data
    df = clean_price_data(df)
    df = calculate_price_per_gram(df)
    
    # Analyze pricing
    analyze_pricing(df)
    
    # Create visualizations
    visualize_data(df)
    
    print("\nAnalysis complete!")

if __name__ == "__main__":
    main() 