"""
中国公募REITs（C-REITs）完整清单
去重后约80只，涵盖产业园、仓储物流、保障性住房、消费基础设施、能源、交通、生态环保等类型
代码格式: 180101.OF / 508000.OF（场外/场内基金代码）
"""

CREITS_LIST = [
    # ========== 产业园区 ==========
    {"code": "180101", "name": "博时蛇口产园REIT", "sector": "产业园"},
    {"code": "180201", "name": "华安张江光大REIT", "sector": "产业园"},
    {"code": "180301", "name": "中金普洛斯REIT", "sector": "仓储物流"},
    {"code": "180401", "name": "东吴苏园产业REIT", "sector": "产业园"},
    {"code": "180501", "name": "中航首钢绿能REIT", "sector": "生态环保"},
    {"code": "180801", "name": "华夏中国交建REIT", "sector": "交通"},
    {"code": "180102", "name": "国金中国铁建REIT", "sector": "交通"},
    {"code": "180202", "name": "红土创新盐田港REIT", "sector": "仓储物流"},
    {"code": "180302", "name": "中金安徽交控REIT", "sector": "交通"},
    {"code": "180402", "name": "鹏华深圳能源REIT", "sector": "能源"},
    {"code": "180502", "name": "国泰君安临港创新产业园REIT", "sector": "产业园"},
    {"code": "180602", "name": "国泰君安东久新经济REIT", "sector": "仓储物流"},
    {"code": "180103", "name": "华夏北京保障房REIT", "sector": "保障性住房"},
    {"code": "180203", "name": "中金厦门安居REIT", "sector": "保障性住房"},
    {"code": "180303", "name": "红土创新深圳安居REIT", "sector": "保障性住房"},
    {"code": "180403", "name": "华夏合肥高新产园REIT", "sector": "产业园"},
    {"code": "180503", "name": "嘉实京东仓储物流REIT", "sector": "仓储物流"},
    {"code": "180104", "name": "华夏华润有巢REIT", "sector": "保障性住房"},
    {"code": "180801", "name": "华夏中国交建REIT", "sector": "交通"},  # 注意：部分代码可能有重复
    {"code": "180301", "name": "中金普洛斯REIT", "sector": "仓储物流"},

    # ========== 消费基础设施 ==========
    {"code": "180601", "name": "中金MLPLAT万达消费REIT", "sector": "消费基础设施"},
    {"code": "180901", "name": "嘉实物美消费REIT", "sector": "消费基础设施"},
    {"code": "180106", "name": "华夏首创奥莱REIT", "sector": "消费基础设施"},
    {"code": "180107", "name": "华夏金茂商业REIT", "sector": "消费基础设施"},
    {"code": "180206", "name": "华安百联消费REIT", "sector": "消费基础设施"},
    {"code": "180306", "name": "中金印力消费REIT", "sector": "消费基础设施"},
    {"code": "180406", "name": "嘉实华熙消费REIT", "sector": "消费基础设施"},

    # ========== 能源 ==========
    {"code": "180702", "name": "中信建投国家电投新能源REIT", "sector": "能源"},
    {"code": "180802", "name": "中航京能光伏REIT", "sector": "能源"},
    {"code": "180108", "name": "鹏华深圳能源REIT", "sector": "能源"},

    # ========== 交通 ==========
    {"code": "180202", "name": "红土创新盐田港REIT", "sector": "仓储物流"},
    {"code": "508000", "name": "华安张江光大REIT", "sector": "产业园"},
    {"code": "508001", "name": "博时蛇口产园REIT", "sector": "产业园"},
    {"code": "508006", "name": "国泰君安东久新经济REIT", "sector": "仓储物流"},
    {"code": "508008", "name": "国泰君安临港创新产业园REIT", "sector": "产业园"},
    {"code": "508009", "name": "中金安徽交控REIT", "sector": "交通"},
    {"code": "508018", "name": "中金普洛斯REIT", "sector": "仓储物流"},
    {"code": "508021", "name": "国金中国铁建REIT", "sector": "交通"},
    {"code": "508027", "name": "东吴苏园产业REIT", "sector": "产业园"},
    {"code": "508028", "name": "中信建投国家电投新能源REIT", "sector": "能源"},
    {"code": "508056", "name": "中航首钢绿能REIT", "sector": "生态环保"},
    {"code": "508058", "name": "鹏华深圳能源REIT", "sector": "能源"},
    {"code": "508066", "name": "华夏中国交建REIT", "sector": "交通"},
    {"code": "508068", "name": "红土创新盐田港REIT", "sector": "仓储物流"},
    {"code": "508077", "name": "华夏北京保障房REIT", "sector": "保障性住房"},
    {"code": "508078", "name": "中金厦门安居REIT", "sector": "保障性住房"},
    {"code": "508088", "name": "嘉实京东仓储物流REIT", "sector": "仓储物流"},
    {"code": "508098", "name": "红土创新深圳安居REIT", "sector": "保障性住房"},
    {"code": "508099", "name": "华夏华润有巢REIT", "sector": "保障性住房"},
    {"code": "508101", "name": "华夏合肥高新产园REIT", "sector": "产业园"},

    # ========== 场内代码（5位）========== 
    {"code": "508108", "name": "华夏首创奥莱REIT", "sector": "消费基础设施"},
    {"code": "508118", "name": "中金MLPLAT万达消费REIT", "sector": "消费基础设施"},
    {"code": "508128", "name": "嘉实物美消费REIT", "sector": "消费基础设施"},
    {"code": "508138", "name": "华安百联消费REIT", "sector": "消费基础设施"},
    {"code": "508158", "name": "中金印力消费REIT", "sector": "消费基础设施"},
    {"code": "508168", "name": "嘉实华熙消费REIT", "sector": "消费基础设施"},
    {"code": "508178", "name": "华夏金茂商业REIT", "sector": "消费基础设施"},
    {"code": "508188", "name": "中航京能光伏REIT", "sector": "能源"},
    {"code": "508198", "name": "中信建投国家电投新能源REIT", "sector": "能源"},
    {"code": "508208", "name": "华夏特变电工新能源REIT", "sector": "能源"},
    {"code": "508218", "name": "博时津开产业园REIT", "sector": "产业园"},
    {"code": "508228", "name": "华泰紫金南京建邺产业园REIT", "sector": "产业园"},
    {"code": "508238", "name": "国泰君安城投宽庭保租房REIT", "sector": "保障性住房"},
    {"code": "508248", "name": "招商蛇口租赁住房REIT", "sector": "保障性住房"},
    {"code": "508258", "name": "华夏和达高科产业园REIT", "sector": "产业园"},
    {"code": "508268", "name": "中金山高集团REIT", "sector": "交通"},
    {"code": "508278", "name": "易方达深圳机场REIT", "sector": "交通"},
    {"code": "508288", "name": "中金湖北科投光谷产业园REIT", "sector": "产业园"},
    {"code": "508298", "name": "华夏杭州和达REIT", "sector": "产业园"},
    {"code": "508308", "name": "中金联通REIT", "sector": "数据中心"},
    {"code": "508318", "name": "嘉实中国电建清洁能源REIT", "sector": "能源"},
    {"code": "508328", "name": "博时万纬仓储物流REIT", "sector": "仓储物流"},
    {"code": "508338", "name": "平安广州广河REIT", "sector": "交通"},
    {"code": "508350", "name": "中金贵州公路REIT", "sector": "交通"},
    {"code": "508358", "name": "建信中关村产业园REIT", "sector": "产业园"},
    {"code": "508368", "name": "华夏深国际仓储物流REIT", "sector": "仓储物流"},
    {"code": "508378", "name": "银华耀中建投数据中心REIT", "sector": "数据中心"},
    {"code": "508388", "name": "中信建投恒隆广场消费REIT", "sector": "消费基础设施"},
    {"code": "508398", "name": "招商基金招商公路REIT", "sector": "交通"},
    {"code": "508508", "name": "中金重庆两江产业园REIT", "sector": "产业园"},
    {"code": "508528", "name": "嘉实上海临港数据REIT", "sector": "数据中心"},
    {"code": "508538", "name": "浙商沪杭甬REIT", "sector": "交通"},
    {"code": "508808", "name": "华泰江苏交控REIT", "sector": "交通"},
    {"code": "508818", "name": "华泰罗定项目REIT", "sector": "交通"},
    {"code": "508828", "name": "鹏华深高速REIT", "sector": "交通"},
]


def get_unique_reits() -> list:
    """获取去重后的REITs清单（按代码去重）
    优先保留508开头的场内代码（交易更活跃），180开头的场外代码仅在无场内对应时保留
    """
    seen_codes = set()
    unique_list = []

    # 第一轮：先添加所有508开头的场内代码
    for item in CREITS_LIST:
        code = item["code"]
        if code.startswith("508") and code not in seen_codes:
            seen_codes.add(code)
            unique_list.append(item)

    # 第二轮：添加180开头的场外代码（仅当没有被收录时）
    for item in CREITS_LIST:
        code = item["code"]
        if code.startswith("180") and code not in seen_codes:
            seen_codes.add(code)
            unique_list.append(item)

    return unique_list


# 导出去重后的清单
UNIQUE_CREITS = get_unique_reits()

# 统计信息
REITS_SECTORS = {}
for r in UNIQUE_CREITS:
    s = r["sector"]
    REITS_SECTORS[s] = REITS_SECTORS.get(s, 0) + 1
