# Data Collection Script for FOMC Project - Based on Excel Indicators
# Collects economic indicators from the Excel file with hierarchical structure

import sys
import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import openpyxl

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fred_api import FredAPI
from data.preprocessing import DataPreprocessor
from database.connection import get_db, init_db, engine
from database.base import Base
from database.models import IndicatorCategory, EconomicIndicator, EconomicDataPoint

# Load environment variables
load_dotenv()

def parse_excel_indicators(excel_path):
    """
    Parse the Excel file to extract indicators with hierarchical structure
    Returns a dictionary with categories and their indicators
    """
    # Load the Excel file
    df = pd.read_excel(excel_path)
    
    # Initialize data structures
    categories = {}
    indicators = []
    current_category = None
    current_subcategory = None
    subcategory_id = 1
    
    # Process each row
    for _, row in df.iterrows():
        sector = row['板块']
        indicator_name = row['经济指标']
        indicator_english = row['Indicator']
        fred_code = row['FRED 代码']
        
        # Skip empty rows
        if pd.isna(sector) or pd.isna(indicator_name):
            continue
            
        # Check if this is a new category
        if sector != current_category:
            current_category = sector
            current_subcategory = None
            if sector not in categories:
                categories[sector] = {
                    'id': len(categories) + 1,
                    'name': sector,
                    'subcategories': {},
                    'indicators': []
                }
        
        # Check if this is a subcategory (no FRED code)
        if pd.isna(fred_code) or fred_code == indicator_name:
            current_subcategory = indicator_name
            subcategory_id += 1
            if current_subcategory not in categories[sector]['subcategories']:
                categories[sector]['subcategories'][current_subcategory] = {
                    'id': subcategory_id,
                    'name': current_subcategory,
                    'indicators': []
                }
        # This is an actual indicator with FRED code
        elif not pd.isna(fred_code):
            indicator = {
                'name': indicator_name,
                'english_name': indicator_english,
                'fred_code': fred_code,
                'category': current_category,
                'subcategory': current_subcategory
            }
            
            # Add to the appropriate category/subcategory
            if current_subcategory:
                categories[sector]['subcategories'][current_subcategory]['indicators'].append(indicator)
            else:
                categories[sector]['indicators'].append(indicator)
            
            indicators.append(indicator)
    
    return categories, indicators

def initialize_database():
    """
    Initialize the database by creating tables
    """
    print("Initializing database...")
    try:
        # Create tables directly using Base metadata
        Base.metadata.create_all(bind=engine)
        print("Database tables created successfully.")
        # Force commit to ensure tables are created
        from sqlalchemy import text
        db = next(get_db())
        db.commit()
        db.close()
        return True
    except Exception as e:
        print(f"Error initializing database: {e}")
        return False

def clear_existing_data():
    """
    Clear all existing data from the database
    """
    print("Clearing existing data from database...")
    try:
        db = next(get_db())
        
        # Delete all data points first (due to foreign key constraints)
        db.query(EconomicDataPoint).delete()
        
        # Delete all indicators
        db.query(EconomicIndicator).delete()
        
        # Delete all categories
        db.query(IndicatorCategory).delete()
        
        db.commit()
        db.close()
        print("Existing data cleared successfully.")
        return True
    except Exception as e:
        print(f"Error clearing existing data: {e}")
        return False

def create_category_hierarchy(categories, db):
    """
    Create the category hierarchy in the database
    Returns a dictionary mapping category names to IDs
    """
    category_map = {}
    subcategory_map = {}
    
    for category_name, category_data in categories.items():
        # Create main category
        main_category = IndicatorCategory(
            name=category_name,
            level=1,
            sort_order=category_data['id']
        )
        db.add(main_category)
        db.flush()  # Get the ID without committing
        category_map[category_name] = main_category.id
        
        # Create subcategories
        for subcategory_name, subcategory_data in category_data['subcategories'].items():
            subcategory = IndicatorCategory(
                name=subcategory_name,
                parent_id=main_category.id,
                level=2,
                sort_order=subcategory_data['id']
            )
            db.add(subcategory)
            db.flush()  # Get the ID without committing
            subcategory_map[f"{category_name}_{subcategory_name}"] = subcategory.id
    
    return category_map, subcategory_map

def collect_and_store_economic_data(excel_path, start_date='2018-01-01'):
    """
    Collect economic data from FRED based on Excel indicators and store it in the database
    """
    print(f"Collecting economic data from {start_date} onwards based on {excel_path}...")
    
    # Parse Excel file to get indicators
    categories, indicators = parse_excel_indicators(excel_path)
    print(f"Found {len(categories)} categories and {len(indicators)} indicators in Excel file.")
    
    # Initialize database
    if not initialize_database():
        print("Failed to initialize database. Exiting...")
        return
    
    # Clear existing data
    if not clear_existing_data():
        print("Failed to clear existing data. Exiting...")
        return
    
    # Get database session
    try:
        db = next(get_db())
    except Exception as e:
        print(f"Error getting database session: {e}")
        return
    
    try:
        # Create category hierarchy
        category_map, subcategory_map = create_category_hierarchy(categories, db)
        print("Category hierarchy created successfully.")
        
        # Initialize FRED API client
        try:
            fred = FredAPI()
            print("FRED API client initialized successfully.")
        except Exception as e:
            print(f"Error initializing FRED API client: {e}")
            return
        
        # Initialize data preprocessor
        preprocessor = DataPreprocessor()
        
        collected_count = 0
        
        for indicator in indicators:
            print(f"\nCollecting data for {indicator['name']} ({indicator['fred_code']})...")
            
            try:
                # Get series information from FRED
                series_info = fred.get_series_info(indicator['fred_code'])
                if 'seriess' in series_info and len(series_info['seriess']) > 0:
                    fred_info = series_info['seriess'][0]
                else:
                    fred_info = {}
                
                # Determine category ID
                category_id = category_map[indicator['category']]
                if indicator['subcategory']:
                    subcategory_key = f"{indicator['category']}_{indicator['subcategory']}"
                    if subcategory_key in subcategory_map:
                        category_id = subcategory_map[subcategory_key]
                
                # Create new indicator record
                new_indicator = EconomicIndicator(
                    name=indicator['name'],
                    english_name=indicator['english_name'],
                    code=indicator['fred_code'],
                    description=fred_info.get('title', ''),
                    frequency=fred_info.get('frequency', ''),
                    units=fred_info.get('units', ''),
                    seasonal_adjustment=fred_info.get('seasonal_adjustment', ''),
                    category_id=category_id
                )
                db.add(new_indicator)
                db.flush()  # Get the ID without committing
                
                # Get series data
                series_data = fred.get_series(
                    indicator['fred_code'], 
                    observation_start=start_date
                )
                
                if 'observations' not in series_data or len(series_data['observations']) == 0:
                    print(f"No data available for {indicator['fred_code']}")
                    continue
                
                # Convert to DataFrame
                df = fred.series_to_dataframe(series_data)
                
                # Clean data
                df_clean = preprocessor.clean_series(df)
                
                # Store data points
                data_points = []
                for _, row in df_clean.iterrows():
                    data_point = EconomicDataPoint(
                        indicator_id=new_indicator.id,
                        date=row['date'],
                        value=row['value']
                    )
                    data_points.append(data_point)
                
                db.add_all(data_points)
                db.commit()
                
                print(f"Successfully collected and stored {len(data_points)} data points for {indicator['name']}")
                collected_count += 1
                
            except Exception as e:
                print(f"Error collecting data for {indicator['fred_code']}: {e}")
                db.rollback()
                continue
        
        print(f"\nData collection completed. Successfully processed {collected_count} out of {len(indicators)} indicators.")
        
    except Exception as e:
        print(f"Error during data collection: {e}")
    finally:
        # Close database session
        try:
            db.close()
        except:
            pass

if __name__ == "__main__":
    # Path to Excel file
    excel_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'US Economic Indicators with FRED Codes.xlsx')
    
    # Collect data from 2018-01-01 onwards
    collect_and_store_economic_data(excel_path, '2018-01-01')