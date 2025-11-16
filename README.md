# FOMC经济数据分析项目

## 项目概述
本项目旨在收集、存储和分析与美联储公开市场委员会(FOMC)决策相关的经济数据。项目包含数据收集、存储和可视化组件，支持从FRED API批量获取51个关键经济指标。

## 项目结构
```
FOMC/
├── config/                 # 配置文件
├── data/                   # 数据处理相关模块
│   ├── collect_economic_data_from_excel.py  # 从Excel文件收集经济数据
│   ├── fred_api.py         # FRED API接口
│   ├── preprocessing.py    # 数据预处理
│   ├── rate_limited_fred_api.py  # 限速FRED API接口
│   └── visualization.py    # 数据可视化
├── database/               # 数据库相关模块
│   ├── base.py            # 共享Base对象
│   ├── connection.py      # 数据库连接
│   └── models.py          # 数据模型
├── docs/                   # 文档和数据文件
│   ├── US Economic Indicators with FRED Codes.xlsx  # 经济指标与FRED代码对照表
│   └── cpi_weights.csv    # CPI权重数据
├── webapp/                 # Web应用程序
│   ├── app.py             # Flask应用程序
│   └── templates/         # HTML模板
├── .env                   # 环境变量配置
├── init_database.py       # 数据库初始化脚本
├── process_all_indicators.py  # 批量处理所有经济指标
├── requirements.txt       # Python依赖包
├── check_database.py      # 检查数据库内容
├── view_data.py           # 查看数据脚本
└── view_schema.py         # 查看数据库结构脚本
```

## 安装依赖
```bash
pip install -r requirements.txt
```

## 环境配置
1. 在FRED网站注册账户并获取API密钥: https://fred.stlouisfed.org/docs/api/api_key.html
2. 将API密钥添加到.env文件中:
```
FRED_API_KEY=your_api_key_here
```

## 使用说明

### 1. 初始化数据库
```bash
python init_database.py
```

### 2. 批量处理所有经济指标（推荐）
```bash
python process_all_indicators.py
```

### 3. 检查数据库内容
```bash
python check_database.py
```

### 4. 查看数据库结构
```bash
python view_schema.py
```

### 5. 查看收集的数据
```bash
python view_data.py
```

### 6. 启动Web数据浏览器
```bash
cd webapp
python app.py
```
访问 http://localhost:5000 查看数据浏览器。

## 数据库结构

### indicator_categories 表
存储经济指标的分类信息:
- id: 主键
- name: 分类名称
- level: 分类层级
- parent_id: 父分类ID

### economic_indicators 表
存储经济指标的定义信息:
- id: 主键
- name: 指标名称
- code: 指标代码
- description: 指标描述
- frequency: 数据频率
- units: 单位
- seasonal_adjustment: 季节性调整信息
- category_id: 分类ID

### economic_data_points 表
存储具体的经济数据点:
- id: 主键
- indicator_id: 外键，关联到economic_indicators表
- date: 数据日期
- value: 数据值

## 收集的经济指标

### 非农就业相关指标（18个）
1. **非农就业总数** (PAYEMS)
2. **分部门新增就业**（13个部门指标）:
   - 采矿业 (USMINE)
   - 建筑业 (USCONS)
   - 制造业 (MANEMP)
   - 批发业 (USWTRADE)
   - 零售业 (USTRADE)
   - 运输仓储业 (USTPU)
   - 公用事业 (CES4422000001)
   - 信息业 (USINFO)
   - 金融活动 (USFIRE)
   - 专业和商业服务 (USPBS)
   - 教育和保健服务 (USEHS)
   - 休闲和酒店业 (USLAH)
   - 其他服务业 (USSERV)
   - 政府 (USGOVT)
3. **失业率指标**（5个U系列指标）:
   - U-3 (UNRATE)
   - U-1 (U1RATE)
   - U-2 (U2RATE)
   - U-4 (U4RATE)
   - U-5 (U5RATE)
   - U-6 (U6RATE)
4. **劳动力市场指标**:
   - 劳动参与率 (CIVPART)
   - 就业率 (EMRATIO)

### CPI相关指标（33个）
1. **总体CPI**:
   - CPI（季调后）(CPIAUCSL)
   - 核心CPI (CPILFESL)
2. **分项CPI**（31个细分指标）:
   - 食品 (CPIUFDSL)
   - 家庭食品 (CUSR0000SAF11)
   - 在外饮食 (CUUR0000SEFV)
   - 能源 (CPIENGSL)
   - 能源商品 (CUSR0000SACE)
   - 燃油和其他燃料 (CUSR0000SEHE)
   - 发动机燃料（汽油） (CUSR0000SETB)
   - 能源服务 (CUSR0000SEHF)
   - 电力 (CUSR0000SEHF01)
   - 公用管道燃气服务 (CUSR0000SEHF02)
   - 核心商品（不含食品和能源类） (CUSR0000SACL1E)
   - 家具和其他家用产品 (CUUS0000SAH31)
   - 服饰 (CPIAPPSL)
   - 交通工具（不含汽车燃料） (CUUS0000SATCLTB)
   - 新车 (CUSR0000SETA01)
   - 二手汽车和卡车 (CUSR0000SETA02)
   - 机动车部件和设备 (CUSR0000SETC)
   - 医疗用品 (CUSR0000SAM1)
   - 酒精饮料 (CUSR0000SAF116)
   - 核心服务（不含能源） (CUSR0000SASLE)
   - 住所 (CUSR0000SAH1)
   - 房租 (CUSR0000SEHA)
   - 水、下水道和垃圾回收 (CUSR0000SEHG)
   - 家庭运营 (CUSR0000SAH3)
   - 医疗服务 (CUSR0000SAM2)
   - 运输服务 (CUSR0000SAS4)

## Web数据浏览器

项目包含一个功能完整的Web界面，用于直观地浏览和分析FOMC相关经济数据。

### 功能特性
1. **响应式设计**：适配桌面和移动设备
2. **指标选择**：从51个关键经济指标中选择查看
3. **时间范围筛选**：支持1年、3年、5年、10年和全部数据的时间范围
4. **数据排序**：支持按日期或数值进行升序/降序排列
5. **可视化图表**：使用Chart.js实现折线图和柱状图展示
6. **数据表格**：以表格形式展示详细数据点
7. **实时刷新**：支持手动刷新获取最新数据
8. **数据摘要**：显示关键指标的最新值和趋势信息

### 技术实现
- **后端**：Python Flask框架
- **前端**：HTML5, CSS3, JavaScript
- **数据库**：SQLAlchemy ORM
- **可视化**：Chart.js
- **UI框架**：Bootstrap 5

## API调用频率控制

项目实现了API调用频率控制机制，避免超出FRED API的调用限制：

1. **限速FRED API**：`rate_limited_fred_api.py` 实现了API调用频率控制
2. **批量处理脚本**：`process_all_indicators.py` 支持批量处理多个指标
3. **错误处理**：实现了重试机制和错误处理

## 开发计划
1. ~~开发数据可视化功能，创建经济指标的趋势图表~~ (已完成)
2. ~~实现定期自动数据收集功能~~ (已完成)
3. ~~添加更多经济指标到收集列表~~ (已完成)
4. ~~开发Web界面以更直观地展示数据~~ (已完成)
5. 实现数据分析和预测功能
6. 添加更多数据源
7. 优化API调用效率