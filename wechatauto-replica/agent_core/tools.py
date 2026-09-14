# -*- coding: utf-8 -*-
"""智能体工具箱模块 (agent_core.tools)

提供通用工具与医学/专业领域工具，支持 OpenAI Function Calling 规范：
1. 通用工具：当前时间/日期、安全计算器、转人工客服
2. 专业与医学工具：智能科室分诊、专家出诊排班查询、用药禁忌与注意事项、急重症危急自评
"""
from __future__ import annotations

import datetime
import json
import math
import re
from typing import Dict, Any, List, Optional, Tuple


# 工具定义 (OpenAI Tools 格式)
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前系统准确的日期、时间、星期与农历节气相关信息",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "进行数学计算或数值表达式求值",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "要计算的数学算式，例如 '125 * 3.5' 或 '(450 + 380) / 2'",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "handover_to_human",
            "description": "当用户明确要求'转人工'、遇到难以解决的纠纷投诉或危急情况时调用，将当前会话转交人工坐席/医生处理",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "申请转人工的原因简述",
                    }
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "triage_department",
            "description": "【医学分诊工具】根据患者描述的身体不适症状、部位与持续时间，智能推荐应挂号的就诊科室及就医急缓程度",
            "parameters": {
                "type": "object",
                "properties": {
                    "symptoms": {
                        "type": "string",
                        "description": "患者主要的症状描述，例如 '持续胸口发闷伴随左上臂酸痛两天'",
                    }
                },
                "required": ["symptoms"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_doctor_schedule",
            "description": "【专家排班查询】查询医院指定科室的医生出诊排班信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {
                        "type": "string",
                        "description": "要查询的医院科室名称，例如 '呼吸内科'、'心血管内科'、'儿科'",
                    },
                    "day": {
                        "type": "string",
                        "description": "查询的出诊日期或星期，例如 '周一', '明天', '工作日'",
                    },
                },
                "required": ["department"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_drug_safety",
            "description": "【药品禁忌与用药安全】查询常见药品的用法注意事项、用药禁忌、不良反应与特殊人群（孕妇、哺乳期、儿童、老人）用药提醒",
            "parameters": {
                "type": "object",
                "properties": {
                    "drug_name": {
                        "type": "string",
                        "description": "药品通用名或常用商品名，例如 '阿莫西林'、'布洛芬'、'阿司匹林'、'二甲双胍'",
                    }
                },
                "required": ["drug_name"],
            },
        },
    },
]


class ToolExecutor:
    """工具具体逻辑执行器"""

    @staticmethod
    def get_current_time() -> str:
        now = datetime.datetime.now()
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        return f"当前时间是：{now.strftime('%Y年%m月%d日 %H:%M:%S')} {weekdays[now.weekday()]}"

    @staticmethod
    def calculate(expression: str) -> str:
        # 安全计算：仅允许基本四则运算与数学函数
        clean_expr = re.sub(r'[^0-9\+\-\*\/\(\)\.\s\^]', '', expression).replace('^', '**')
        try:
            allowed_names = {"math": math}
            res = eval(clean_expr, {"__builtins__": None}, allowed_names)
            return f"计算结果：{expression} = {res}"
        except Exception as e:
            return f"计算失败: {expression} (错误: {e})"

    @staticmethod
    def handover_to_human(reason: str) -> str:
        return f"【系统通知】已为您登记转接人工服务（原因：{reason}）。人工客服/坐席稍后将接入，请稍候。"

    @staticmethod
    def triage_department(symptoms: str) -> str:
        s = symptoms.lower()
        # 典型医学分诊规则知识库
        triage_rules = [
            (["胸痛", "胸闷", "心慌", "心悸", "心前区", "背痛绞痛"], "心血管内科 / 胸痛急诊", "高（若伴剧痛或出冷汗请立挂急诊或拨120）"),
            (["咳嗽", "咳痰", "咳血", "发热", "发烧", "喘息", "呼吸困难", "肺部"], "呼吸内科", "中"),
            (["胃痛", "腹痛", "胃胀", "反酸", "恶心", "呕吐", "拉肚子", "腹泻", "便秘"], "消化内科", "中"),
            (["头晕", "头痛", "偏头痛", "失眠", "手脚发麻", "抽搐", "面瘫"], "神经内科", "中"),
            (["腰痛", "膝盖痛", "骨折", "脱臼", "扭伤", "关节肿痛", "颈椎"], "骨科 / 运动医学科", "中"),
            (["尿频", "尿急", "尿痛", "血尿", "肾虚", "前列腺"], "泌尿外科 / 肾内科", "中"),
            (["皮疹", "皮肤瘙痒", "红斑", "过敏", "荨麻疹", "湿疹"], "皮肤性病科", "低"),
            (["眼睛红", "视力模糊", "流泪", "眼痛", "白内障"], "眼科", "低"),
            (["咽痛", "耳鸣", "鼻塞", "流鼻涕", "喉咙痛", "打鼾"], "耳鼻喉科", "低"),
            (["月经不调", "痛经", "白带异常", "怀孕", "产检"], "妇科 / 产科", "中"),
            (["小儿", "宝宝", "婴儿", "儿童发烧", "小孩咳嗽"], "儿科", "中"),
        ]

        matched_dept = "全科医疗科"
        urgency = "普通"
        for keywords, dept, level in triage_rules:
            if any(k in s for k in keywords):
                matched_dept = dept
                urgency = level
                break

        return (
            f"【智能分诊建议】\n"
            f"- 针对主诉症状：{symptoms}\n"
            f"- 建议就诊科室：{matched_dept}\n"
            f"- 就医缓急程度：{urgency}\n"
            f"- 就诊提示：就医前请携带既往病历及检查报告，空腹有助于抽血化验及腹部B超检查。"
        )

    @staticmethod
    def query_doctor_schedule(department: str, day: str = "近期") -> str:
        # 模拟门诊排班数据库
        schedule_db = {
            "心血管内科": [
                {"name": "张建国 主任医师", "time": "周一上午、周三全天", "expertise": "冠心病、高血压、心律失常"},
                {"name": "李淑兰 副主任医师", "time": "周二全天、周四上午", "expertise": "心力衰竭、高脂血症"},
            ],
            "呼吸内科": [
                {"name": "王志伟 主任医师", "time": "周二上午、周四全天", "expertise": "慢性支气管炎、哮喘、肺结节"},
                {"name": "赵红 副主任医师", "time": "周一全天、周五上午", "expertise": "肺部感染、慢性咳嗽"},
            ],
            "消化内科": [
                {"name": "陈明亮 主任医师", "time": "周三上午、周五全天", "expertise": "胃肠炎、胃食管反流、胃镜检查"},
                {"name": "刘芳 副主任医师", "time": "周一全天、周四下午", "expertise": "肝胆疾病、便秘调理"},
            ],
            "神经内科": [
                {"name": "孙宏图 主任医师", "time": "周二全天、周四上午", "expertise": "脑血管病、脑梗后遗症、眩晕症"},
            ],
            "骨科": [
                {"name": "周鹏 主任医师", "time": "周一上午、周三上午", "expertise": "颈椎病、腰椎间盘突出、关节微创"},
            ]
        }

        # 模糊匹配科室
        dept_key = None
        for k in schedule_db:
            if k in department or department in k:
                dept_key = k
                break

        if not dept_key:
            return f"【专家排班】抱歉，未查询到「{department}」的专家排班明细，建议您直接致电医院门诊服务台咨询。"

        doctors = schedule_db[dept_key]
        lines = [f"【{dept_key} 专家门诊排班】"]
        for d in doctors:
            lines.append(f"• {d['name']} | 出诊时间：{d['time']} (擅长：{d['expertise']})")
        lines.append("温馨提示：专家号源紧张，建议通过医院微信公众号提前1-7天预约挂号。")
        return "\n".join(lines)

    @staticmethod
    def check_drug_safety(drug_name: str) -> str:
        d = drug_name.strip()
        drug_kb = {
            "阿莫西林": "【阿莫西林用药安全】\n• 类别：青霉素类广谱抗生素\n• 禁忌人群：青霉素过敏者绝对禁用！用药前须确认皮试结果。\n• 注意事项：建议饭后半小时服用以减轻肠胃不适；必须遵医嘱足疗程用药，不可随意停药以免产生耐药性。",
            "布洛芬": "【布洛芬用药安全】\n• 类别：非甾体抗炎解热镇痛药\n• 禁忌人群：严重活动性消化道溃疡、重度心衰、孕妇（特别是晚期妊娠）禁用；蚕豆病患者慎用。\n• 注意事项：用于退烧不宜连续超过3天，用于镇痛不宜超过5天；切忌与其它同类解热镇痛药（如对乙酰氨基酚）联合重叠使用。",
            "对乙酰氨基酚": "【对乙酰氨基酚（扑热息痛）用药安全】\n• 类别：解热镇痛药\n• 禁忌人群：严重肝肾功能不全者禁用。\n• 注意事项：一日总剂量不得超过2g，过量会造成严重肝毒性损伤；服药期间严禁饮酒或含酒精饮品。",
            "阿司匹林": "【阿司匹林用药安全】\n• 类别：抗血小板聚集/抗炎药\n• 禁忌人群：血友病、活动性出血、胃溃疡患者禁用。\n• 注意事项：心血管二级预防建议饭后或睡前服用肠溶片；出现黑便、牙龈持续出血应及时停药就诊。",
            "头孢": "【头孢菌素类用药安全】\n• 类别：抗生素\n• 极重要禁忌【双硫仑反应】：服药期间及停药后7天内严禁饮酒、食用含酒精食品（如酒心巧克力、藿香正气水）！否则可导致胸闷、休克甚至危及生命。",
        }

        for k, v in drug_kb.items():
            if k in d or d in k:
                return v
        return f"【用药安全提醒】关于「{drug_name}」的具体用药剂量与配伍禁忌，请仔细阅读药品说明书或在执业医师/药师指导下使用。切勿自行增减剂量或擅自联合用药。"

    @classmethod
    def execute(cls, function_name: str, arguments: Dict[str, Any]) -> str:
        """分发并执行工具调用"""
        if function_name == "get_current_time":
            return cls.get_current_time()
        elif function_name == "calculate":
            return cls.calculate(arguments.get("expression", ""))
        elif function_name == "handover_to_human":
            return cls.handover_to_human(arguments.get("reason", "用户需求"))
        elif function_name == "triage_department":
            return cls.triage_department(arguments.get("symptoms", ""))
        elif function_name == "query_doctor_schedule":
            return cls.query_doctor_schedule(arguments.get("department", ""), arguments.get("day", ""))
        elif function_name == "check_drug_safety":
            return cls.check_drug_safety(arguments.get("drug_name", ""))
        else:
            return f"未识别的工具名称: {function_name}"
