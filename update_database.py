import sqlite3
import pandas as pd

def update_database():
    # 连接到数据库
    conn = sqlite3.connect('fomc_data.db')
    cursor = conn.cursor()
    
    # 读取Excel文件
    excel_file = 'docs/US Economic Indicators with FRED Codes.xlsx'
    df = pd.read_excel(excel_file)
    
    # 获取当前经济指标数据
    cursor.execute("SELECT id, name, code FROM economic_indicators")
    indicators = cursor.fetchall()
    
    # 创建指标名称到ID的映射
    indicator_map = {name: id for id, name, fred_code in indicators}
    
    # 获取当前分类数据
    cursor.execute("SELECT id, name FROM indicator_categories")
    categories = cursor.fetchall()
    
    # 创建分类名称到ID的映射
    category_map = {name: id for id, name in categories}
    
    # 更新分类的排序
    # 根据Excel文件，非农就业在前，CPI在后
    cursor.execute("UPDATE indicator_categories SET sort_order = 1 WHERE name = '非农就业'")
    cursor.execute("UPDATE indicator_categories SET sort_order = 2 WHERE name = 'CPI'")
    
    # 为分项CPI创建子类别
    # 首先检查是否已有"分项CPI"类别
    cursor.execute("SELECT id FROM indicator_categories WHERE name = '分项CPI'")
    result = cursor.fetchone()
    
    if result:
        cpi_subcategory_id = result[0]
    else:
        # 创建"分项CPI"类别，作为CPI的子类别
        cursor.execute("SELECT id FROM indicator_categories WHERE name = 'CPI'")
        cpi_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO indicator_categories (name, parent_id, level, sort_order) VALUES (?, ?, ?, ?)",
                      ('分项CPI', cpi_id, 2, 1))
        cpi_subcategory_id = cursor.lastrowid
    
    # 创建分项CPI的子类别
    cpi_subcategories = ['食品类', '能源类', '核心商品类', '核心服务类']
    cpi_subcategory_ids = {}
    
    for subcategory_name in cpi_subcategories:
        cursor.execute("SELECT id FROM indicator_categories WHERE name = ?", (subcategory_name,))
        result = cursor.fetchone()
        
        if result:
            cpi_subcategory_ids[subcategory_name] = result[0]
        else:
            # 创建子类别，作为分项CPI的子类别
            cursor.execute("INSERT INTO indicator_categories (name, parent_id, level, sort_order) VALUES (?, ?, ?, ?)",
                          (subcategory_name, cpi_subcategory_id, 3, len(cpi_subcategory_ids) + 1))
            cpi_subcategory_ids[subcategory_name] = cursor.lastrowid
    
    # 根据数据库中的实际指标名称更新排序
    # 非农就业指标排序
    nonfarm_employment_indicators = [
        '非农就业总数',
        'U-3',  # 失业率
        '劳动参与率',
        '就业率',
        # 以下是分部门新增就业
        '采矿业',
        '建筑业',
        '制造业',
        '批发业',
        '零售业',
        '运输仓储业',
        '公用事业',
        '信息业',
        '金融活动',
        '专业和商业服务',
        '教育和保健服务',
        '休闲和酒店业',
        '其他服务业',
        '政府'
    ]
    
    # CPI指标排序
    cpi_indicators = [
        'CPI（季调后）',
        '核心 CPI'
    ]
    
    # 分项CPI指标排序 - 食品类
    cpi_food_indicators = [
        '食品',
        '家庭食品',
        '在外饮食'
    ]
    
    # 分项CPI指标排序 - 能源类
    cpi_energy_indicators = [
        '能源',
        '能源商品',
        '燃油和其他燃料',
        '发动机燃料（汽油）',
        '能源服务',
        '电力',
        '公用管道燃气服务'
    ]
    
    # 分项CPI指标排序 - 核心商品类
    cpi_core_goods_indicators = [
        '核心商品（不含食品和能源类）',
        '家具和其他家用产品',
        '服饰',
        '交通工具（不含汽车燃料）',
        '新车',
        '二手汽车和卡车',
        '机动车部件和设备',
        '医疗用品',
        '酒精饮料'
    ]
    
    # 分项CPI指标排序 - 核心服务类
    cpi_core_services_indicators = [
        '核心服务（不含能源）',
        '住所',
        '房租',
        '水、下水道和垃圾回收',
        '家庭运营',
        '医疗服务',
        '运输服务'
    ]
    
    # 更新非农就业指标的排序
    for i, indicator_name in enumerate(nonfarm_employment_indicators, 1):
        if indicator_name in indicator_map:
            cursor.execute("UPDATE economic_indicators SET sort_order = ? WHERE name = ?", (i, indicator_name))
    
    # 更新CPI指标的排序
    for i, indicator_name in enumerate(cpi_indicators, 1):
        if indicator_name in indicator_map:
            cursor.execute("UPDATE economic_indicators SET sort_order = ? WHERE name = ?", (i, indicator_name))
    
    # 更新分项CPI指标的排序和类别
    # 食品类
    for i, indicator_name in enumerate(cpi_food_indicators, 1):
        if indicator_name in indicator_map:
            cursor.execute("UPDATE economic_indicators SET sort_order = ?, category_id = ? WHERE name = ?", 
                          (i, cpi_subcategory_ids['食品类'], indicator_name))
    
    # 能源类
    for i, indicator_name in enumerate(cpi_energy_indicators, 1):
        if indicator_name in indicator_map:
            cursor.execute("UPDATE economic_indicators SET sort_order = ?, category_id = ? WHERE name = ?", 
                          (i, cpi_subcategory_ids['能源类'], indicator_name))
    
    # 核心商品类
    for i, indicator_name in enumerate(cpi_core_goods_indicators, 1):
        if indicator_name in indicator_map:
            cursor.execute("UPDATE economic_indicators SET sort_order = ?, category_id = ? WHERE name = ?", 
                          (i, cpi_subcategory_ids['核心商品类'], indicator_name))
    
    # 核心服务类
    for i, indicator_name in enumerate(cpi_core_services_indicators, 1):
        if indicator_name in indicator_map:
            cursor.execute("UPDATE economic_indicators SET sort_order = ?, category_id = ? WHERE name = ?", 
                          (i, cpi_subcategory_ids['核心服务类'], indicator_name))
    
    # 提交更改
    conn.commit()
    print("数据库更新完成")
    
    # 验证更新
    print("\n分类排序:")
    cursor.execute("SELECT id, name, sort_order FROM indicator_categories WHERE parent_id IS NULL ORDER BY sort_order")
    for row in cursor.fetchall():
        print(f"ID: {row[0]}, 名称: {row[1]}, 排序: {row[2]}")
    
    print("\n非农就业指标排序:")
    cursor.execute("""
        SELECT ei.id, ei.name, ei.sort_order 
        FROM economic_indicators ei
        JOIN indicator_categories ic ON ei.category_id = ic.id
        WHERE ic.name = '非农就业'
        ORDER BY ei.sort_order
    """)
    for row in cursor.fetchall():
        print(f"ID: {row[0]}, 名称: {row[1]}, 排序: {row[2]}")
    
    print("\nCPI指标排序:")
    cursor.execute("""
        SELECT ei.id, ei.name, ei.sort_order 
        FROM economic_indicators ei
        JOIN indicator_categories ic ON ei.category_id = ic.id
        WHERE ic.name = 'CPI'
        ORDER BY ei.sort_order
    """)
    for row in cursor.fetchall():
        print(f"ID: {row[0]}, 名称: {row[1]}, 排序: {row[2]}")
    
    print("\n分项CPI指标排序:")
    cursor.execute("""
        SELECT ei.id, ei.name, ei.sort_order 
        FROM economic_indicators ei
        JOIN indicator_categories ic ON ei.category_id = ic.id
        WHERE ic.name = '分项CPI'
        ORDER BY ei.sort_order
    """)
    for row in cursor.fetchall():
        print(f"ID: {row[0]}, 名称: {row[1]}, 排序: {row[2]}")
    
    # 关闭连接
    conn.close()

if __name__ == "__main__":
    update_database()