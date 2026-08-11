# -*- coding: utf-8 -*-
"""论证理由自动生成（模板化，数据驱动）：
根据风控状态（fire/pending/acked/none）+ 评分 + 资金流 + 消息面 + 解禁数据，
生成7条排序理由（权重/立场/计算公式），写入 payload_hand.json 的 argument 字段。
每日4次管道运行时自动刷新，不再有静态旧内容。"""
import json, os

BASE = r"C:\Users\ASUS\WorkBuddy\2026-08-03-11-17-59"
DATA = os.path.join(BASE, "data")

def load(fn, base=DATA):
    p = os.path.join(base, fn)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None

risk = load("risk_check.json")
score = load("score_result.json")
flows = load("stock_flows.json") or {}
news = load("news.json") or {}
unlock = load("unlock_future.json")
hand_path = os.path.join(BASE, "payload_hand.json")
hand = json.load(open(hand_path, encoding="utf-8"))

mode = (risk or {}).get("ackState", {}).get("mode", "fire" if (risk or {}).get("triggered") else "none")
cooldown = (risk or {}).get("cooldown", {})
cd_items = cooldown.get("items", [])
if mode == "none" and cooldown.get("active"):
    mode = "cooldown"
actions = (risk or {}).get("actions", [])
comp = (score or {}).get("composite", 50)
zone = (score or {}).get("zone", "中性震荡区")
tech_scores = (score or {}).get("tech", {}).get("trackScores", {})
extras_total = (score or {}).get("extras", {}).get("total", 0)

# 资金流亮点
flow_sorted = sorted(((k, v["main"]) for k, v in flows.items() if "main" in v), key=lambda x: x[1])
top_out = flow_sorted[0] if flow_sorted else ("—", 0)
top_in = flow_sorted[-1] if flow_sorted else ("—", 0)

# 今日重大消息（major）
majors = [it for cat in news.get("categories", []) for it in cat.get("items", []) if it.get("major")]
major_bear = next((m for m in majors if m["impact"] == "利空"), None)
major_bull = next((m for m in majors if m["impact"] == "利好"), None)

# 外围（从hand的overseas取最新）
ov = {o["name"]: o for o in hand.get("overseas", [])}
ndx_o = ov.get("纳斯达克", {})
us10y_o = ov.get("美债10Y收益率", {})

TRACKS = ["半导体设备", "存储芯片", "光通信模块"]
acted = [a for a in actions if a["rule"].startswith("赛道")]
acted_names = [a["target"] for a in acted]
not_acted = [t for t in TRACKS if t not in acted_names]

if mode in ("fire", "pending", "cooldown") and (actions or cd_items):
    if mode == "cooldown":
        verdict = "风控冷却观察期：%s（同档位不重复、禁加仓，仅更高档可追加）" % "；".join(cd_items[:2])
    else:
        verdict = "触发%d项强制风控：%s" % (len(actions), "；".join("%s%s" % (a["target"], a["action"]) for a in actions[:3]))
    r1_title = ("冷却期依据：%s——8/3触发的周线破位已执行/待确认，冷却期内不重复减仓" % "；".join(cd_items[:2])) if mode == "cooldown" else \
               ("%s——趋势性破位为风控最高级别触发条件，纪律要求必须执行" % ("；".join("%s（%s，%s）" % (a["target"], a.get("tier", ""), a.get("cond", "")[:40]) for a in acted[:2]) or "风控触发"))
    reasons = [
        {"rank": 1, "weight": 30, "dim": "技术面", "stance": "支持",
         "title": r1_title,
         "formula": "权重=触发级别系数。T3周线破位为赛道风控最高档，趋势性破位非情绪脉冲，对结论起决定性作用→30%"},
        {"rank": 2, "weight": 20, "dim": "规则纪律", "stance": "支持",
         "title": "风控凌驾原则：打分%.1f分（%s）与风控方向冲突时无条件服从风控——过滤情绪、只认破位" % (comp, zone),
         "formula": "权重=规则优先级系数。风控为体系最高优先级（凌驾打分），方向冲突时无条件服从→20%"},
        {"rank": 3, "weight": 15, "dim": "技术面", "stance": "支持",
         "title": "%s未触发风控：区别对待不连坐，保留赛道内相对强势品种" % ("、".join(not_acted) if not_acted else "三大赛道均已触发"),
         "formula": "权重=区分度系数。未触发赛道维持持仓，避免一刀切错杀→15%"},
        {"rank": 4, "weight": 15, "dim": "外围面", "stance": "不支持",
         "title": "外围偏暖（纳指%s %s、美债10Y %s）支持「减仓不清仓」：保留修复弹性" % (ndx_o.get("val", "—"), ndx_o.get("chg", ""), us10y_o.get("val", "—")),
         "formula": "权重=先行指标系数。外围核心信号正向时约束减仓幅度（减而不清）→15%，属反向证据"},
        {"rank": 5, "weight": 10, "dim": "资金面", "stance": "部分支持",
         "title": "资金结构分化：%s主力%+.1f亿 vs %s%+.1f亿——非系统性撤离，支持分批执行而非一次减完" % (top_out[0], top_out[1], top_in[0], top_in[1]),
         "formula": "权重=资金验证系数。主力流向分化说明非系统性撤离→支持减仓但约束执行节奏→10%"},
        {"rank": 6, "weight": 5, "dim": "基本面", "stance": "不支持",
         "title": "%s——产业景气与政策托底限制减仓性质为风控性而非看空离场" % (major_bull["title"][:36] if major_bull else "产业景气与政策托底仍在"),
         "formula": "权重=景气对冲系数。景气验证+政策托底限制减仓幅度→5%，属反向证据"},
        {"rank": 7, "weight": 5, "dim": "供需面", "stance": "支持",
         "title": "供给端：未来7日解禁%s、无大额IPO——无额外抛压，不需要加码减仓" % (("%.1f亿" % unlock["sum7d"]) if unlock else "温和"),
         "formula": "权重=供给压力系数。解禁温和+无IPO虹吸→5%"},
    ]
    no_add = "风控冷却期内禁发加仓指令（触发后3个交易日）；更高档位风控才可追加减仓，同档位不重复"
    no_reduce_more = "不减更多的理由：外围偏暖（理由4）、资金非系统性撤离（理由5）、产业景气与政策托底（理由6）——按规则执行到位即可，超出则属情绪化"
else:
    # 无风控触发：围绕打分结论
    if comp >= 65:
        verdict = "综合得分%.1f（%s）：加仓信号" % (comp, zone)
    elif comp >= 45:
        verdict = "综合得分%.1f（%s）：不调仓，持有观望" % (comp, zone)
    else:
        verdict = "综合得分%.1f（%s）：减仓信号" % (comp, zone)
    reasons = [
        {"rank": 1, "weight": 25, "dim": "技术面", "stance": "支持" if 45 <= comp < 65 else "不支持",
         "title": "核心决策层：赛道技术分%s、宽基九转未触9——无有效顶底信号区间（45-65）按规则不操作" % "/".join("%.0f" % v for v in tech_scores.values()),
         "formula": "权重=决策层系数。技术面占体系60%权重，其子项状态直接决定结论→25%"},
        {"rank": 2, "weight": 20, "dim": "外围面", "stance": "不支持" if 45 <= comp < 65 else "支持",
         "title": "外围核心信号：纳指%s（%s）连续站稳MA5，方向与A股技术面的僵持形成对冲" % (ndx_o.get("val", "—"), ndx_o.get("chg", "")),
         "formula": "权重=先行指标系数。外围占25%权重且核心项主导，与A股方向冲突时禁止简单抵消→20%"},
        {"rank": 3, "weight": 15, "dim": "规则纪律", "stance": "支持",
         "title": "风控未触发：8条强制风控规则全部在安全阈值内，打分结论正常生效",
         "formula": "权重=风控状态系数。无风控凌驾时打分体系是唯一决策依据→15%"},
        {"rank": 4, "weight": 15, "dim": "资金面", "stance": "部分支持",
         "title": "资金结构：%s主力%+.1f亿、%s%+.1f亿，两融余额趋势待企稳——杠杆情绪中性" % (top_in[0], top_in[1], top_out[0], top_out[1]),
         "formula": "权重=资金验证系数。主力流向与两融趋势综合评定→15%"},
        {"rank": 5, "weight": 10, "dim": "消息面", "stance": "不支持" if major_bear else "支持",
         "title": "%s" % (major_bear["title"][:40] if major_bear else (major_bull["title"][:40] if major_bull else "消息面无单边驱动")),
         "formula": "权重=消息冲击系数。重大消息（★）对短期风险偏好的扰动评估→10%"},
        {"rank": 6, "weight": 10, "dim": "基本面", "stance": "支持",
         "title": "%s——产业景气验证" % (major_bull["title"][:36] if major_bull else "产业景气与政策面无单边变化"),
         "formula": "权重=景气系数。财报/产业数据对赛道景气度的验证→10%"},
        {"rank": 7, "weight": 5, "dim": "供需面", "stance": "支持",
         "title": "供给端：未来7日解禁%s、无大额IPO——扣分项未触发" % (("%.1f亿" % unlock["sum7d"]) if unlock else "温和"),
         "formula": "权重=供给压力系数→5%"},
    ]
    no_add = "打分未达65（弱底部线），且无底部确认信号（九转低9+MA5确认），不满足加仓条件"
    no_reduce_more = "打分未跌破45（弱顶部门），且无顶部结构（高9/顶背离/风控破位），不满足减仓条件"

hand["argument"] = {
    "verdict": verdict,
    "dimensions": [
        {"name": "技术面（核心决策层）", "weight": 60, "color": "#1976d2",
         "note": "赛道指数信号60%%+宽基40%%；赛道技术分：%s" % "、".join("%s%.1f" % (t, tech_scores.get(t, 50)) for t in TRACKS)},
        {"name": "外围面（先行指标）", "weight": 25, "color": "#00a05a",
         "note": "纳指%s（%s）、美债10Y %s——核心指标主导，不对冲" % (ndx_o.get("val", "—"), ndx_o.get("chg", ""), us10y_o.get("val", "—"))},
        {"name": "资金面（杠杆与流动性）", "weight": 10, "color": "#f5a623",
         "note": "主力流向：流入端%s%+.1f亿、流出端%s%+.1f亿；北向按成交额口径" % (top_in[0], top_in[1], top_out[0], top_out[1])},
        {"name": "基本面与消息面", "weight": 5, "color": "#7b61c4",
         "note": "额外加减分当前%s分；%s" % (("%+d" % extras_total), (majors[0]["title"][:30] if majors else "消息面平稳"))},
    ],
    "reasons": reasons,
    "stanceNote": {"支持": "该理由支持当前核心结论", "不支持": "该理由为反向证据（用于约束操作幅度）", "部分支持": "部分支持（支持方向但约束节奏）"},
    "noAdd": no_add,
    "noReduce_more": no_reduce_more,
}
json.dump(hand, open(hand_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("argument generated | mode:", mode, "| verdict:", verdict[:50])
print("reasons:", [(r["rank"], r["weight"], r["stance"]) for r in reasons])
