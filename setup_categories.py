import sqlite3
import pandas as pd

def setup_categories():
    # 连接到数据库
    conn = sqlite3.connect('fomc_data.db')
    cursor = conn.cursor()
    
    # 获取当前经济指标数据
    cursor.execute("SELECT id, name, code, category_id FROM economic_indicators")
    indicators = cursor.fetchall()
    
    # 创建指标名称到ID的映射
    indicator_map = {name: id for id, name, code, category_id in indicators}
    
    # 获取当前分类数据
    cursor.execute("SELECT id, name FROM indicator_categories")
    categories = cursor.fetchall()
    
    # 创建分类名称到ID的映射
    category_map = {name: id for id, name in categories}
    
    # 更新分类的排序
    # 根据Excel文件，非农就业在前，CPI在后
    cursor.execute("UPDATE indicator_categories SET sort_order = 1 WHERE name = '非农就业'")
    cursor.execute("UPDATE indicator_categories SET sort_order = 2 WHERE name = 'CPI'")
    
    # 创建非农就业的子类别
    nonfarm_subcategories = [
        ('分部门新增就业', category_map['非农就业'], 1),
        ('季调各类型失业率', category_map['非农就业'], 2)
    ]
    
    for name, parent_id, sort_order in nonfarm_subcategories:
        cursor.execute("INSERT INTO indicator_categories (name, parent_id, level, sort_order) VALUES (?, ?, ?, ?)",
                      (name, parent_id, 2, sort_order))
    
    # 创建CPI的子类别
    cursor.execute("INSERT INTO indicator_categories (name, parent_id, level, sort_order) VALUES (?, ?, ?, ?)",
                  ('分项CPI', category_map['CPI'], 2, 1))
    
    # 获取分项CPI的ID
    cursor.execute("SELECT id FROM indicator_categories WHERE name = '分项CPI' AND parent_id = ?", (category_map['CPI'],))
    cpi_subcategory_id = cursor.fetchone()[0]
    
    # 创建分项CPI的子类别
    cpi_subcategories = [
        ('食品类', cpi_subcategory_id, 1),
        ('能源类', cpi_subcategory_id, 2),
        ('核心商品类', cpi_subcategory_id, 3),
        ('核心服务类', cpi_subcategory_id, 4)
    ]
    
    cpi_subcategory_ids = {}
    for name, parent_id, sort_order in cpi_subcategories:
        cursor.execute("INSERT INTO indicator_categories (name, parent_id, level, sort_order) VALUES (?, ?, ?, ?)",
                      (name, parent_id, 3, sort_order))
        cursor.execute("SELECT id FROM indicator_categories WHERE name = ? AND parent_id = ?", (name, parent_id))
        cpi_subcategory_ids[name] = cursor.fetchone()[0]
    
    # 根据数据库中的实际指标名称更新排序
    # 非农就业指标排序
    nonfarm_employment_indicators = [
        '非农就业总数',
        'U-3',  # 失业率
        '劳动参与率',
        '就业率'
    ]
    
    # 分部门新增就业指标排序
    sector_employment_indicators = [
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
    
    # 季调各类型失业率指标排序
    unemployment_indicators = [
        'U-1',
        'U-2',
        'U-4',
        'U-5',
        'U-6'
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
    
    # 获取分类ID
    cursor.execute("SELECT id FROM indicator_categories WHERE name = '分部门新增就业'")
    sector_employment_id = cursor.fetchone()[0]
    
    cursor.execute("SELECT id FROM indicator_categories WHERE name = '季调各类型失业率'")
    unemployment_id = cursor.fetchone()[0]
    
    # 更新非农就业指标的排序
    for i, indicator_name in enumerate(nonfarm_employment_indicators, 1):
        if indicator_name in indicator_map:
            cursor.execute("UPDATE economic_indicators SET sort_order = ? WHERE name = ?", (i, indicator_name))
    
    # 更新分部门新增就业指标的排序和类别
    for i, indicator_name in enumerate(sector_employment_indicators, 1):
        if indicator_name in indicator_map:
            cursor.execute("UPDATE economic_indicators SET sort_order = ?, category_id = ? WHERE name = ?", 
                          (i, sector_employment_id, indicator_name))
    
    # 更新失业率指标的排序和类别
    for i, indicator_name in enumerate(unemployment_indicators, 1):
        if indicator_name in indicator_map:
            cursor.execute("UPDATE economic_indicators SET sort_order = ?, category_id = ? WHERE name = ?", 
                          (i, unemployment_id, indicator_name))
    
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
    cursor.execute("SELECT id, name, parent_id, level, sort_order FROM indicator_categories ORDER BY parent_id, level, sort_order")
    for row in cursor.fetchall():
        print(f"ID: {row[0]}, 名称: {row[1]}, 父级ID: {row[2]}, 级别: {row[3]}, 排序: {row[4]}")
    
    # 关闭连接
    conn.close()

if __name__ == "__main__":
    setup_categories()