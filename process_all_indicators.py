# Script to process all indicators from Excel file

import sys
import os
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import IndicatorCategory, EconomicIndicator, EconomicDataPoint
from database.base import Base
from data.rate_limited_fred_api import RateLimitedFredAPI

def process_all_indicators():
    """
    Process all indicators from Excel file and fetch their data
    """
    # Initialize the FRED API with rate limiting (30 requests per minute)
    fred_api = RateLimitedFredAPI(requests_per_minute=30)
    
    # Connect to database
    engine = create_engine("sqlite:///fomc_data.db")
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Default date range (2018 to latest)
    default_start_date = "2018-01-01"
    default_end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Read Excel file
    excel_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                  'docs', 'US Economic Indicators with FRED Codes.xlsx')
    
    if not os.path.exists(excel_file_path):
        print(f"Excel file not found at {excel_file_path}")
        return
    
    df = pd.read_excel(excel_file_path, sheet_name='Sheet1')
    
    print(f"Total rows in Excel file: {len(df)}")
    
    # Replace empty strings with NaN for easier handling
    df = df.replace('', pd.NA)
    
    # Fill forward the board name to handle empty cells
    df['板块'] = df['板块'].ffill()
    
    # Fill forward the FRED code to handle empty cells
    df['FRED 代码'] = df['FRED 代码'].ffill()
    
    # Remove rows where both 板块 and 经济指标 are empty
    df = df.dropna(subset=['板块', '经济指标'], how='all')
    
    print(f"Total rows after processing: {len(df)}")
    print("First few rows:")
    print(df.head(10))
    
    # Track current subcategory for each board
    current_subcategories = {}
    
    try:
        # Process each row
        for index, row in df.iterrows():
            board_name = row['板块']
            indicator_name = row['经济指标']
            english_name = row['Indicator']
            fred_code = row['FRED 代码']
            
            print(f"\nProcessing row {index+1}: {board_name} - {indicator_name} ({fred_code})")
            
            # Clean up the FRED code by removing any special characters
            fred_code = str(fred_code).strip()
            # Remove zero-width spaces and other invisible characters
            fred_code = fred_code.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '')
            
            # Skip rows where FRED code is empty or the same as indicator name (category rows)
            if not fred_code or fred_code == indicator_name:
                print(f"Skipping category row: {indicator_name}")
                continue
            
            # Skip duplicate rows (same FRED code as previous row)
            if index > 0 and fred_code == str(df.iloc[index-1]['FRED 代码']).strip().replace('\u200b', '').replace('\u200c', '').replace('\u200d', ''):
                print(f"Skipping duplicate row for {indicator_name} ({fred_code})")
                continue
            
            # Get or create board category (level 1)
            board_category = session.query(IndicatorCategory).filter_by(name=board_name).first()
            if not board_category:
                board_category = IndicatorCategory(name=board_name, level=1)
                session.add(board_category)
                session.commit()
                print(f"Created category: {board_name} (level 1)")
            
            # Check if this is a subcategory (like "分部门新增就业" or "分项 CPI")
            if indicator_name in ['分部门新增就业', '分项 CPI', '季调各类型失业率']:
                # This is a subcategory (level 2)
                subcategory = session.query(IndicatorCategory).filter_by(name=indicator_name).first()
                if not subcategory:
                    subcategory = IndicatorCategory(name=indicator_name, parent_id=board_category.id, level=2)
                    session.add(subcategory)
                    session.commit()
                    print(f"Created subcategory: {indicator_name} under {board_name} (level 2)")
                
                current_subcategories[board_name] = subcategory
                continue
            
            # Determine category for this indicator
            category_id = board_category.id
            
            # Check if we have a current subcategory for this board
            if board_name in current_subcategories:
                # Check if this indicator belongs to the current subcategory
                subcategory_name = current_subcategories[board_name].name
                
                # Assign indicators to appropriate subcategories based on their characteristics
                if subcategory_name == '分部门新增就业' and indicator_name in [
                    '采矿业', '建筑业', '制造业', '批发业', '零售业', '运输仓储业', 
                    '公用事业', '信息业', '金融活动', '专业和商业服务', 
                    '教育和保健服务', '休闲和酒店业', '其他服务业', '政府'
                ]:
                    category_id = current_subcategories[board_name].id
                elif subcategory_name == '分项 CPI' and indicator_name in [
                    '食品', '家庭食品', '在外饮食', '能源', '能源商品', 
                    '燃油和其他燃料', '发动机燃料（汽油）', '能源服务', '电力', 
                    '公用管道燃气服务', '核心商品（不含食品和能源类）', 
                    '家具和其他家用产品', '服饰', '交通工具（不含汽车燃料）', 
                    '新车', '二手汽车和卡车', '机动车部件和设备', '医疗用品', 
                    '酒精饮料', '核心服务（不含能源）', '住所', '房租', 
                    '水、下水道和垃圾回收', '家庭运营', '医疗服务', '运输服务'
                ]:
                    category_id = current_subcategories[board_name].id
                elif subcategory_name == '季调各类型失业率' and indicator_name in [
                    'U-1', 'U-2', 'U-3', 'U-4', 'U-5', 'U-6'
                ]:
                    category_id = current_subcategories[board_name].id
            
            # Get or create indicator
            indicator = session.query(EconomicIndicator).filter_by(code=fred_code).first()
            
            if not indicator:
                # Get metadata from FRED API
                try:
                    metadata = fred_api.get_series_info(fred_code)
                    series_info = metadata.get('seriess', [{}])[0]
                    
                    # Extract metadata fields
                    description = series_info.get('description', '')
                    frequency = series_info.get('frequency', '')
                    units = series_info.get('units', '')
                    seasonal_adjustment = series_info.get('seasonal_adjustment', '')
                    last_updated = series_info.get('last_updated', None)
                    
                    if last_updated:
                        last_updated = datetime.strptime(last_updated, '%Y-%m-%d %H:%M:%S')
                except Exception as e:
                    print(f"Warning: Could not fetch metadata for {fred_code}: {str(e)}")
                    description = english_name if english_name else indicator_name
                    frequency = ''
                    units = ''
                    seasonal_adjustment = ''
                    last_updated = None
                
                # Create new indicator
                indicator = EconomicIndicator(
                    name=indicator_name,
                    code=fred_code,
                    english_name=english_name,
                    description=description,
                    frequency=frequency,
                    units=units,
                    seasonal_adjustment=seasonal_adjustment,
                    last_updated=last_updated,
                    category_id=category_id
                )
                
                session.add(indicator)
                session.commit()
                print(f"Created indicator: {indicator_name} ({fred_code})")
            else:
                # Update existing indicator if needed
                if indicator.name != indicator_name or indicator.english_name != english_name or indicator.category_id != category_id:
                    indicator.name = indicator_name
                    indicator.english_name = english_name
                    indicator.category_id = category_id
                    session.commit()
                    print(f"Updated indicator: {indicator_name} ({fred_code})")
            
            # Fetch and store data
            try:
                # Fetch data from FRED API
                series_data = fred_api.get_series(
                    fred_code, 
                    observation_start=default_start_date, 
                    observation_end=default_end_date
                )
                
                # Convert to DataFrame
                df_data = fred_api.series_to_dataframe(series_data)
                
                # Store data points
                count = 0
                for _, row_data in df_data.iterrows():
                    # Check if data point already exists
                    existing = session.query(EconomicDataPoint).filter_by(
                        indicator_id=indicator.id, 
                        date=row_data['date']
                    ).first()
                    
                    if not existing:
                        data_point = EconomicDataPoint(
                            indicator_id=indicator.id,
                            date=row_data['date'],
                            value=row_data['value']
                        )
                        session.add(data_point)
                        count += 1
                
                session.commit()
                print(f"Stored {count} new data points for {indicator_name} ({fred_code})")
                
            except Exception as e:
                print(f"Error fetching data for {fred_code}: {str(e)}")
                session.rollback()
        
        print("\nSuccessfully processed all indicators from Excel file")
        
    except Exception as e:
        print(f"Error processing Excel file: {str(e)}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    process_all_indicators()