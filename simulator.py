"""电商模拟器 v2 — 多商品 + AI竞品 + 供应链 + 市场周期

API端点（兼容v1）:
  GET  /competitor-price   竞品均价
  GET  /supplier-price     供应商价格
  GET  /daily-sales        销售报告
  POST /pricing            设置售价 (body: {"price": 12.5})
  POST /ad-spend           投放广告 (body: {"budget": 100})
  POST /inventory          补货 (body: {"units": 50})
  POST /tick               推进一天
  GET  /market-status      市场全局状态
  POST /reset              重置模拟器

新增v2端点:
  GET  /products           商品列表及各自状态
  POST /product-pricing    设置某商品售价 (body: {"product_id": "a", "price": 15})
  GET  /competitors        各商品竞品信息
  GET  /market-forecast    市场需求预测
"""

import json
import logging
import math
import random
import uuid
from datetime import datetime
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("simulator")

app = Flask(__name__)

# ── 商品定义 ──
PRODUCT_CATEGORIES = {
    "a": {"name": "电子产品", "base_demand": 1000,  "base_cost": 50,  "volatility": 0.3, "ad_elasticity": 0.5},
    "b": {"name": "服装配饰", "base_demand": 2000,  "base_cost": 20,  "volatility": 0.4, "ad_elasticity": 0.3},
    "c": {"name": "食品饮料", "base_demand": 5000,  "base_cost": 8,   "volatility": 0.2, "ad_elasticity": 0.2},
    "d": {"name": "家用电器", "base_demand": 500,   "base_cost": 200, "volatility": 0.35,"ad_elasticity": 0.4},
}

# ── 市场状态 ──

class ProductState:
    __slots__ = ("id", "price", "inventory", "supplier_price", "supplier_trend", "units_sold_today",
                 "total_units_sold", "total_revenue", "total_cost", "ad_budget", "demand_multiplier")
    def __init__(self, pid: str, cat: dict):
        self.id = pid
        self.price = cat["base_cost"] * 1.8  # 初始售价=成本x1.8
        self.inventory = 200
        self.supplier_price = cat["base_cost"]
        self.supplier_trend = "stable"
        self.units_sold_today = 0
        self.total_units_sold = 0
        self.total_revenue = 0.0
        self.total_cost = 0.0
        self.ad_budget = 0.0
        self.demand_multiplier = 1.0

class Market:
    def __init__(self):
        self.day = 0
        self.products: dict[str, ProductState] = {}
        for pid, cat in PRODUCT_CATEGORIES.items():
            self.products[pid] = ProductState(pid, cat)
        self.competitors: dict[str, list[dict]] = {}  # pid -> [{name, price}]
        self.market_cycle = 0  # 0-99, 影响需求
        self.events: list[str] = []
        self.event_log: list[str] = []
        self.ai_competitors_count = 5
        self._init_competitors()

    def _init_competitors(self):
        for pid, ps in self.products.items():
            cat = PRODUCT_CATEGORIES[pid]
            base = cat["base_cost"]
            comps = []
            for i in range(self.ai_competitors_count):
                comps.append({
                    "name": f"竞品{chr(65+i)}",
                    "price": round(base * random.uniform(1.3, 2.5), 2),
                })
            self.competitors[pid] = comps

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.event_log.append(f"[Day{self.day} {ts}] {msg}")

    def _calc_demand(self, pid: str, ps: ProductState) -> int:
        """计算某商品当天的需求"""
        cat = PRODUCT_CATEGORIES[pid]
        base = cat["base_demand"]
        # 市场周期：正弦波 ±30%
        cycle = 1.0 + 0.3 * math.sin(self.market_cycle * math.pi / 25)
        # 竞争对手压力：竞品价格越低，需求越低
        avg_comp = sum(c["price"] for c in self.competitors[pid]) / len(self.competitors[pid])
        price_ratio = ps.price / avg_comp if avg_comp > 0 else 1.0
        # 价格弹性：价格高于竞品均价10%，需求下降20%
        price_factor = 1.0 - 2.0 * max(0, price_ratio - 1.0)
        # 广告影响
        ad_factor = 1.0 + cat["ad_elasticity"] * math.log1p(ps.ad_budget) / 10 if ps.ad_budget > 0 else 1.0
        # 需求乘数
        demand = int(base * cycle * price_factor * ad_factor * ps.demand_multiplier)
        return max(1, demand)

    def tick_ai_competitors(self):
        """AI竞品调整价格 — 模拟真实市场反应"""
        for pid, ps in self.products.items():
            comps = self.competitors[pid]
            cat = PRODUCT_CATEGORIES[pid]
            for c in comps:
                # 竞品有概率根据我的价格调整
                if random.random() < 0.3:
                    # 如果我的价格低于竞品平均，竞品降价竞争
                    avg_comp = sum(x["price"] for x in comps) / len(comps)
                    if ps.price < avg_comp * 0.9:
                        c["price"] = round(c["price"] * random.uniform(0.92, 0.98), 2)
                    elif ps.price > avg_comp * 1.2:
                        c["price"] = round(c["price"] * random.uniform(1.02, 1.08), 2)
                    else:
                        # 随机波动
                        c["price"] = round(c["price"] * random.uniform(0.95, 1.05), 2)
                    # 保证不低于成本
                    c["price"] = max(cat["base_cost"] * 1.1, c["price"])

    def tick_suppliers(self):
        """供应商价格波动"""
        for pid, ps in self.products.items():
            change = random.uniform(-0.08, 0.08)
            ps.supplier_price = round(ps.supplier_price * (1 + change), 2)
            cat = PRODUCT_CATEGORIES[pid]
            ps.supplier_price = max(cat["base_cost"] * 0.7, min(cat["base_cost"] * 3.0, ps.supplier_price))
            if change > 0.05:
                ps.supplier_trend = "up"
            elif change < -0.05:
                ps.supplier_trend = "down"
            else:
                ps.supplier_trend = "stable"

    def tick_sales(self):
        """结算当日销售"""
        for pid, ps in self.products.items():
            demand = self._calc_demand(pid, ps)
            sold = min(demand, ps.inventory)
            ps.units_sold_today = sold
            ps.total_units_sold += sold
            revenue = sold * ps.price
            cost = sold * ps.supplier_price + ps.ad_budget
            ps.total_revenue += revenue
            ps.total_cost += cost
            ps.inventory -= sold
            ps.ad_budget = 0  # 广告每日重置

    def trigger_random_event(self):
        """触发随机混沌事件"""
        if random.random() > 0.25:  # 25%概率触发
            return
        event_type = random.choice(["price_war", "supply_shock", "ad_crash", "demand_surge", "new_competitor", "quality_scandal"])
        pid = random.choice(list(self.products.keys()))
        ps = self.products[pid]
        cat = PRODUCT_CATEGORIES[pid]
        
        if event_type == "price_war":
            # 竞品集体降价20%
            for c in self.competitors[pid]:
                c["price"] = round(c["price"] * 0.8, 2)
            self._log(f"⚠️ 价格战! {cat['name']}竞品集体降价20%")
            
        elif event_type == "supply_shock":
            # 供应商价格暴涨50%
            ps.supplier_price = round(ps.supplier_price * 1.5, 2)
            ps.supplier_trend = "up"
            self._log(f"⚠️ 供应冲击! {cat['name']}原材料成本暴涨50%")
            
        elif event_type == "ad_crash":
            # 广告渠道故障
            ps.ad_budget = 0
            self._log(f"⚠️ 广告崩溃! {cat['name']}广告渠道故障")
            
        elif event_type == "demand_surge":
            # 需求暴增
            ps.demand_multiplier = 2.0
            self._log(f"⚠️ 需求暴增! {cat['name']}市场需求翻倍")
            
        elif event_type == "new_competitor":
            # 新竞品入场
            self.competitors[pid].append({
                "name": f"新竞品{chr(70+len(self.competitors[pid]))}",
                "price": round(cat["base_cost"] * random.uniform(1.2, 1.8), 2),
            })
            self._log(f"⚠️ 新对手入场! {cat['name']}出现新竞品")
            
        elif event_type == "quality_scandal":
            # 质量丑闻，需求暴跌
            ps.demand_multiplier = 0.3
            self._log(f"⚠️ 质量丑闻! {cat['name']}需求暴跌70%")

    def advance_day(self):
        """推进一天"""
        self.tick_sales()
        self.tick_ai_competitors()
        self.tick_suppliers()
        self.trigger_random_event()
        self.day += 1
        self.market_cycle = (self.market_cycle + 1) % 100
        # 重置需求乘数（逐步恢复）
        for ps in self.products.values():
            if ps.demand_multiplier < 1.0:
                ps.demand_multiplier = min(1.0, ps.demand_multiplier + 0.1)
            elif ps.demand_multiplier > 1.0:
                ps.demand_multiplier = max(1.0, ps.demand_multiplier - 0.1)
        # 每隔几天清一下日志
        if self.day % 10 == 0:
            self.event_log = self.event_log[-50:]
        self._log(f"→ 第{self.day}天开始")


# ── 全局市场实例 ──
market = Market()


# ══════════════════════════════════════════
# v1 兼容端点（单商品 = 商品"a"）
# ══════════════════════════════════════════

@app.route("/competitor-price")
def competitor_price():
    ps = market.products["a"]
    comps = market.competitors["a"]
    avg = round(sum(c["price"] for c in comps) / len(comps), 2) if comps else 0
    return jsonify({"avg_price": avg, "count": len(comps), "prices": [c["price"] for c in comps[:3]]})

@app.route("/supplier-price")
def supplier_price():
    ps = market.products["a"]
    return jsonify({"price": ps.supplier_price, "trend": ps.supplier_trend})

@app.route("/daily-sales")
def daily_sales():
    total_revenue = sum(p.total_revenue for p in market.products.values())
    total_cost = sum(p.total_cost for p in market.products.values())
    total_units = sum(p.total_units_sold for p in market.products.values())
    return jsonify({
        "revenue": round(total_revenue, 2),
        "cost": round(total_cost, 2),
        "profit": round(total_revenue - total_cost, 2),
        "units_sold": total_units,
    })

@app.route("/pricing", methods=["POST"])
def set_pricing():
    data = request.get_json() or {}
    new_price = float(data.get("price", market.products["a"].price))
    market.products["a"].price = round(new_price, 2)
    market._log(f"商品A: 售价调整为 ${market.products['a'].price}")
    return jsonify({"product": "a", "price": market.products["a"].price, "status": "ok"})

@app.route("/ad-spend", methods=["POST"])
def ad_spend():
    data = request.get_json() or {}
    budget = float(data.get("budget", 0))
    # 分摊到所有商品
    for pid, ps in market.products.items():
        ps.ad_budget += budget / len(market.products)
    market._log(f"广告: 投放 ${budget}")
    # 模拟广告效果
    reach = int(budget * random.uniform(50, 200))
    clicks = int(reach * random.uniform(0.01, 0.05))
    return jsonify({"budget": budget, "reach": reach, "clicks": clicks, "status": "ok"})

@app.route("/inventory", methods=["POST"])
def restock():
    data = request.get_json() or {}
    units = int(data.get("units", 100))
    pid = data.get("product_id", "a")
    ps = market.products.get(pid, market.products["a"])
    cost = units * ps.supplier_price
    ps.inventory += units
    ps.total_cost += cost
    market._log(f"商品{pid}: 采购{units}件, 成本${cost:.0f}")
    return jsonify({"product": pid, "units_added": units, "cost": round(cost, 2), "inventory": ps.inventory})

@app.route("/tick", methods=["POST"])
def advance_day():
    market.advance_day()
    return jsonify({"day": market.day, "status": "ok"})

@app.route("/market-status")
def market_status():
    profit = sum(p.total_revenue - p.total_cost for p in market.products.values())
    ps = market.products["a"]
    comps = market.competitors["a"]
    return jsonify({
        "day": market.day,
        "products": len(market.products),
        "supplier_price": ps.supplier_price,
        "supplier_trend": ps.supplier_trend,
        "competitor_price": round(sum(c["price"] for c in comps) / len(comps), 2) if comps else 0,
        "competitor_count": len(comps),
        "my_price": ps.price,
        "my_inventory": ps.inventory,
        "ad_budget": ps.ad_budget,
        "total_revenue": round(profit.comp, 2) if hasattr(profit, 'comp') else round(sum(p.total_revenue for p in market.products.values()), 2),
        "total_cost": round(sum(p.total_cost for p in market.products.values()), 2),
        "total_profit": round(profit, 2),
        "units_sold_today": ps.units_sold_today,
        "total_units_sold": ps.total_units_sold,
    })


# ══════════════════════════════════════════
# v2 新增端点
# ══════════════════════════════════════════

@app.route("/products")
def products():
    """获取所有商品状态"""
    result = {}
    for pid, ps in market.products.items():
        cat = PRODUCT_CATEGORIES[pid]
        result[pid] = {
            "name": cat["name"],
            "price": ps.price,
            "inventory": ps.inventory,
            "supplier_price": ps.supplier_price,
            "units_sold_today": ps.units_sold_today,
            "total_units_sold": ps.total_units_sold,
            "profit": round(ps.total_revenue - ps.total_cost, 2),
        }
    return jsonify(result)

@app.route("/product-pricing", methods=["POST"])
def product_pricing():
    """设置某商品售价"""
    data = request.get_json() or {}
    pid = data.get("product_id", "a")
    price = float(data.get("price", 0))
    if pid not in market.products:
        return jsonify({"error": f"unknown product: {pid}"}), 400
    market.products[pid].price = round(price, 2)
    market._log(f"商品{pid}: 售价调整为 ${price}")
    return jsonify({"product": pid, "price": market.products[pid].price, "status": "ok"})

@app.route("/competitors")
def competitors():
    """各商品竞品信息"""
    result = {}
    for pid, comps in market.competitors.items():
        cat = PRODUCT_CATEGORIES[pid]
        result[pid] = {
            "category": cat["name"],
            "count": len(comps),
            "avg_price": round(sum(c["price"] for c in comps) / len(comps), 2),
            "competitors": comps[:5],
        }
    return jsonify(result)

@app.route("/market-forecast")
def market_forecast():
    """未来几天需求预测"""
    forecasts = {}
    for pid in market.products:
        cat = PRODUCT_CATEGORIES[pid]
        base = cat["base_demand"]
        next_3 = []
        for i in range(1, 4):
            cycle = 1.0 + 0.3 * math.sin((market.market_cycle + i) * math.pi / 25)
            next_3.append(int(base * cycle))
        forecasts[pid] = {"name": cat["name"], "next_3_days": next_3}
    return jsonify(forecasts)

@app.route("/event-log")
def event_log():
    """最近事件日志"""
    return jsonify(market.event_log[-30:])

@app.route("/reset", methods=["POST"])
def reset():
    global market
    market = Market()
    logger.info("模拟器已重置")
    return jsonify({"status": "ok", "day": 0})


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("电商模拟器 v2 启动")
    logger.info(f"商品种类: {len(PRODUCT_CATEGORIES)}")
    logger.info(f"竞品数量: 每个商品 {market.ai_competitors_count} 个AI竞品")
    logger.info("=" * 50)
    logger.info(f"  v1端点: competitor-price, supplier-price, daily-sales,")
    logger.info(f"          pricing, ad-spend, inventory, tick, market-status")
    logger.info(f"  v2端点: products, product-pricing, competitors,")
    logger.info(f"          market-forecast, event-log")
    logger.info(f"  混沌事件: 价格战,供应冲击,广告崩溃,需求暴增,新对手,质量丑闻")
    logger.info("=" * 50)
    app.run(host="0.0.0.0", port=5800, debug=False)
