# Script to check existing indicators in the database

import sys
import os
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import IndicatorCategory, EconomicIndicator, EconomicDataPoint
from database.base import Base

def check_database():
    """
    Check existing indicators and categories in the database
    """
    # Connect to database
    engine = create_engine("sqlite:///fomc_data.db")
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Check categories
        categories = session.query(IndicatorCategory).all()
        print(f"Total categories: {len(categories)}")
        for category in categories:
            print(f"  - {category.name} (ID: {category.id}, Level: {category.level}, Parent: {category.parent_id})")
        
        # Check indicators
        indicators = session.query(EconomicIndicator).all()
        print(f"\nTotal indicators: {len(indicators)}")
        for indicator in indicators:
            print(f"  - {indicator.name} ({indicator.code}) - Category ID: {indicator.category_id}")
        
        # Check data points
        data_points = session.query(EconomicDataPoint).all()
        print(f"\nTotal data points: {len(data_points)}")
        
        # Check data points per indicator
        print("\nData points per indicator:")
        for indicator in indicators:
            count = session.query(EconomicDataPoint).filter_by(indicator_id=indicator.id).count()
            print(f"  - {indicator.name} ({indicator.code}): {count} data points")
    
    finally:
        session.close()

if __name__ == "__main__":
    check_database()