import os
import sys
from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta

# 将项目根目录添加到Python路径中
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import get_db, engine
from database.models import EconomicIndicator, EconomicDataPoint, IndicatorCategory
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, func

app = Flask(__name__, template_folder='templates')

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db_session():
    """获取数据库会话"""
    return SessionLocal()

@app.route('/')
def index():
    """主页路由"""
    return render_template('index.html')

@app.route('/api/indicators')
def get_indicators():
    """获取所有经济指标的层级结构"""
    try:
        db = get_db_session()
        
        # 获取所有顶级分类（板块）
        top_categories = db.query(IndicatorCategory).filter(IndicatorCategory.parent_id.is_(None)).all()
        
        def build_category_hierarchy(category):
            """递归构建分类层级结构"""
            result = {
                'id': category.id,
                'name': category.name,
                'level': category.level,
                'type': 'category',
                'children': []
            }
            
            # 获取子分类
            child_categories = db.query(IndicatorCategory).filter(IndicatorCategory.parent_id == category.id).all()
            for child in child_categories:
                result['children'].append(build_category_hierarchy(child))
            
            # 获取该分类下的指标
            indicators = db.query(EconomicIndicator).filter(EconomicIndicator.category_id == category.id).all()
            for indicator in indicators:
                result['children'].append({
                    'id': indicator.id,
                    'name': indicator.name,
                    'code': indicator.code,
                    'english_name': indicator.english_name,
                    'units': indicator.units,
                    'type': 'indicator'
                })
            
            return result
        
        # 构建完整的层级结构
        hierarchy = []
        for category in top_categories:
            hierarchy.append(build_category_hierarchy(category))
        
        db.close()
        return jsonify(hierarchy)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/summary')
def get_summary():
    """获取经济指标摘要数据"""
    try:
        db = get_db_session()
        
        # 获取所有指标
        indicators = db.query(EconomicIndicator).order_by(EconomicIndicator.id).all()
        
        result = []
        for indicator in indicators:
            # 获取最新数据点
            latest_data_point = db.query(EconomicDataPoint)\
                .filter(EconomicDataPoint.indicator_id == indicator.id)\
                .order_by(EconomicDataPoint.date.desc())\
                .first()
            
            # 获取数据点总数
            data_point_count = db.query(EconomicDataPoint)\
                .filter(EconomicDataPoint.indicator_id == indicator.id)\
                .count()
            
            result.append({
                'id': indicator.id,
                'name': indicator.name,
                'code': indicator.code,
                'units': indicator.units,
                'latest_value': latest_data_point.value if latest_data_point else None,
                'latest_date': latest_data_point.date.strftime('%Y-%m-%d') if latest_data_point else None,
                'data_point_count': data_point_count
            })
        
        db.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/data')
def get_data():
    """获取经济数据点"""
    try:
        indicator_id = request.args.get('indicator_id')
        date_range = request.args.get('date_range', '3Y')  # 默认最近3年
        sort_order = request.args.get('sort_order', 'date_desc')  # 默认按日期降序
        
        db = get_db_session()
        
        # 构建查询
        query = db.query(
            EconomicIndicator.name.label('indicator_name'),
            EconomicIndicator.code.label('indicator_code'),
            EconomicIndicator.units,
            EconomicDataPoint.date,
            EconomicDataPoint.value
        ).join(EconomicDataPoint, EconomicDataPoint.indicator_id == EconomicIndicator.id)
        
        # 添加指标筛选
        if indicator_id:
            query = query.filter(EconomicDataPoint.indicator_id == indicator_id)
        
        # 处理时间范围
        if date_range != 'all':
            end_date = datetime.now()
            if date_range == '1Y':
                start_date = end_date - timedelta(days=365)
            elif date_range == '3Y':
                start_date = end_date - timedelta(days=365*3)
            elif date_range == '5Y':
                start_date = end_date - timedelta(days=365*5)
            elif date_range == '10Y':
                start_date = end_date - timedelta(days=365*10)
            
            query = query.filter(EconomicDataPoint.date >= start_date)
        
        # 处理排序
        if sort_order == 'date_desc':
            query = query.order_by(EconomicDataPoint.date.desc())
        elif sort_order == 'date_asc':
            query = query.order_by(EconomicDataPoint.date.asc())
        elif sort_order == 'value_desc':
            query = query.order_by(EconomicDataPoint.value.desc())
        elif sort_order == 'value_asc':
            query = query.order_by(EconomicDataPoint.value.asc())
        
        # 限制结果数量
        data_points = query.limit(1000).all()
        
        result = []
        for point in data_points:
            result.append({
                'indicator_name': point.indicator_name,
                'indicator_code': point.indicator_code,
                'units': point.units,
                'date': point.date.strftime('%Y-%m-%d'),
                'value': point.value
            })
        
        db.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/chart-data')
def get_chart_data():
    """获取图表数据"""
    try:
        indicator_id = request.args.get('indicator_id')
        date_range = request.args.get('date_range', '3Y')  # 默认最近3年
        
        if not indicator_id:
            return jsonify({'error': '缺少指标ID参数'}), 400
        
        db = get_db_session()
        
        # 获取指标信息
        indicator = db.query(EconomicIndicator.name).filter(EconomicIndicator.id == indicator_id).first()
        
        if not indicator:
            db.close()
            return jsonify({'error': '未找到指定的指标'}), 404
        
        indicator_name = indicator[0]
        
        # 构建查询
        query = db.query(EconomicDataPoint.date, EconomicDataPoint.value)\
            .filter(EconomicDataPoint.indicator_id == indicator_id)
        
        # 处理时间范围
        if date_range != 'all':
            end_date = datetime.now()
            if date_range == '1Y':
                start_date = end_date - timedelta(days=365)
            elif date_range == '3Y':
                start_date = end_date - timedelta(days=365*3)
            elif date_range == '5Y':
                start_date = end_date - timedelta(days=365*5)
            elif date_range == '10Y':
                start_date = end_date - timedelta(days=365*10)
            
            query = query.filter(EconomicDataPoint.date >= start_date)
        
        # 按日期排序
        data_points = query.order_by(EconomicDataPoint.date.asc()).all()
        
        dates = []
        values = []
        
        for point in data_points:
            dates.append(point.date.strftime('%Y-%m-%d'))
            values.append(point.value)
        
        db.close()
        return jsonify({
            'indicator_name': indicator_name,
            'dates': dates,
            'values': values
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/refresh-data', methods=['POST'])
def refresh_data():
    """刷新数据（模拟实现）"""
    try:
        # 实际应用中这里应该包含数据更新逻辑
        # 示例：从外部API获取最新数据并存储到数据库
        # 暂时保留模拟响应
        return jsonify({'message': '数据刷新任务已启动'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)