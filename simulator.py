"""电商运营模拟器 — 提供真实数据反馈的虚拟市场

API:
  GET  /supplier-price  → {"price": 当前采购价, "trend": "up/down/stable"}
  GET  /competitor-price → {"price": 竞品均价, "count": 竞品数}
  POST /ad-spend         → {"cost": 消耗, "impressions": 曝光, "clicks": 点击, "conversions": 转化}
  GET  /daily-sales      → {"revenue": 收入, "units_sold": 销量, "avg_price": 均价, "profit": 利润}
  POST /pricing          → 设置售价
  GET  /market-status    → 全局市场状态
  POST /reset            → 重置模拟器

启动:
  python simulator.py
  # 默认监听 0.0.0.0:5800
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)

# ── 市场状态 ──

class Market:
    def __init__(self):
        self.day = 0
        self.supplier_price = 50.0      # 采购成本
        self.competitor_avg_price = 99.0
        self.competitor_count = random.randint(3, 8)
        self.market_demand = 1000        # 市场总需求
        self.price_sensitivity = 2.0     # 价格弹性

        # 我的状态
        self.my_price = 89.0
        self.my_inventory = 200
        self.ad_budget = 0
        self.total_revenue = 0.0
        self.total_cost = 0.0
        self.units_sold_today = 0
        self.total_units_sold = 0

        # 趋势
        self.supplier_trend = "stable"
        self.competitor_trend = "stable"
        self.demand_trend = "stable"

        # 事件日志
        self.events: list[str] = []

    def _log(self, msg: str) -> None:
        self.events.append(f"[Day {self.day}] {msg}")
        if len(self.events) > 50:
            self.events.pop(0)

    def tick(self) -> None:
        """模拟一天过去，市场波动"""
        self.day += 1

        # ── 随机混乱事件 (35%概率) ──
        chaos_event = ""
        if random.random() < 0.35:
            chaos_events = [
                "supplier_shortage",      # 供应商短缺 → 采购价飙3倍
                "price_war",              # 竞品价格战 → 竞品价暴跌50%
                "ad_channel_down",        # 广告渠道崩溃 → 广告无效
                "inventory_rot",          # 库存腐烂 → 库存莫名减少
                "demand_crash",           # 需求骤降 → 市场需求跌60%
                "tax_inspection",         # 税务检查 → 追加成本
            ]
            chaos_type = random.choice(chaos_events)
            chaos_event = f"⚡ 混沌事件: "

            if chaos_type == "supplier_shortage":
                self.supplier_price = round(self.supplier_price * random.uniform(2.0, 3.5), 2)
                self.supplier_trend = "crisis"
                chaos_event += f"供应商短缺! 采购价飙至${self.supplier_price}"
            elif chaos_type == "price_war":
                self.competitor_avg_price = round(self.competitor_avg_price * random.uniform(0.4, 0.6), 2)
                self.competitor_count = min(12, self.competitor_count + random.randint(1, 3))
                chaos_event += f"竞品发动价格战! 均价暴跌至${self.competitor_avg_price}"
            elif chaos_type == "ad_channel_down":
                self._ad_blocked_days = 3
                chaos_event += "广告渠道故障! 3天内广告投放无效"
            elif chaos_type == "inventory_rot":
                lost = int(self.my_inventory * random.uniform(0.1, 0.3))
                self.my_inventory = max(0, self.my_inventory - lost)
                chaos_event += f"库存腐烂! {lost}件报废"
            elif chaos_type == "demand_crash":
                self.market_demand = int(self.market_demand * 0.4)
                chaos_event += f"市场需求骤降60%"
            elif chaos_type == "tax_inspection":
                tax = random.uniform(500, 2000)
                self.total_cost += tax
                chaos_event += f"税务检查! 追加罚款${tax:.0f}"

            self._log(chaos_event)

        # ── 检验广告阻塞 ──
        if hasattr(self, '_ad_blocked_days') and self._ad_blocked_days > 0:
            self._ad_blocked_days -= 1

        # 供应商价格波动 ±15%
        delta = random.uniform(-0.15, 0.15)
        self.supplier_price = round(self.supplier_price * (1 + delta), 2)
        self.supplier_price = max(20, min(120, self.supplier_price))

        if delta > 0.05:
            self.supplier_trend = "up"
        elif delta < -0.05:
            self.supplier_trend = "down"
        else:
            self.supplier_trend = "stable"

        # 竞品价格波动
        delta = random.uniform(-0.10, 0.10)
        self.competitor_avg_price = round(self.competitor_avg_price * (1 + delta), 2)
        self.competitor_avg_price = max(30, min(200, self.competitor_avg_price))

        if random.random() < 0.2:
            self.competitor_count += random.choice([-1, 0, 1])
            self.competitor_count = max(1, self.competitor_count)

        # 市场需求波动
        delta = random.uniform(-0.20, 0.20)
        self.market_demand = int(self.market_demand * (1 + delta))
        self.market_demand = max(200, min(3000, self.market_demand))

        # 我的销量: 价格比竞品低 → 占有率上升
        price_ratio = self.competitor_avg_price / max(self.my_price, 1)
        base_share = 1.0 / (self.competitor_count + 1)
        my_share = base_share * (price_ratio ** self.price_sensitivity)

        # 广告加成
        ad_boost = min(0.3, self.ad_budget / 1000.0)
        my_share += ad_boost

        # 计算销量
        self.units_sold_today = int(self.market_demand * my_share)
        self.units_sold_today = min(self.units_sold_today, self.my_inventory)

        # 财务
        revenue = self.units_sold_today * self.my_price
        cost = self.units_sold_today * self.supplier_price + self.ad_budget
        profit = revenue - cost

        self.total_revenue += revenue
        self.total_cost += cost
        self.total_units_sold += self.units_sold_today
        self.my_inventory -= self.units_sold_today

        self._log(
            f"卖出{self.units_sold_today}件, "
            f"收入${revenue:.0f}, 成本${cost:.0f}, "
            f"利润${profit:.0f}, 库存{self.my_inventory}"
        )

        # 随机事件
        if random.random() < 0.1:
            events = [
                "供应商原料短缺，下周价格可能上涨",
                "新竞争对手进入市场",
                "社交媒体上你的产品获得好评，需求上升20%",
                "竞争对手发起价格战，降价15%",
                "季节性需求高峰到来",
            ]
            event = random.choice(events)
            self._log(f"⚡ 市场事件: {event}")
            if "好评" in event:
                self.market_demand = int(self.market_demand * 1.2)
            if "价格战" in event:
                self.competitor_avg_price *= 0.85

        # 重置每日预算
        self.ad_budget = 0


market = Market()


# ── API ──

@app.route("/supplier-price")
def supplier_price():
    return jsonify({
        "price": market.supplier_price,
        "trend": market.supplier_trend,
        "day": market.day,
    })


@app.route("/competitor-price")
def competitor_price():
    return jsonify({
        "price": market.competitor_avg_price,
        "count": market.competitor_count,
        "trend": market.competitor_trend,
    })


@app.route("/ad-spend", methods=["POST"])
def ad_spend():
    # 广告渠道故障检测
    if hasattr(market, '_ad_blocked_days') and market._ad_blocked_days > 0:
        return jsonify({
            "error": "channel_down",
            "message": f"广告渠道故障中，预计{market._ad_blocked_days}天后恢复",
            "cost": 0,
            "impressions": 0,
            "clicks": 0,
            "conversions": 0,
        }), 503

    data = request.get_json() or {}
    budget = float(data.get("budget", 0))
    market.ad_budget = budget

    cpm = random.uniform(5, 15)  # 千次曝光成本
    impressions = int(budget / cpm * 1000) if budget > 0 else 0
    ctr = random.uniform(0.01, 0.05)
    clicks = int(impressions * ctr)
    conversion_rate = random.uniform(0.02, 0.08)
    conversions = int(clicks * conversion_rate)

    return jsonify({
        "cost": budget,
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "cpm": round(cpm, 2),
        "ctr": f"{ctr:.1%}",
    })


@app.route("/daily-sales")
def daily_sales():
    profit = market.total_revenue - market.total_cost
    return jsonify({
        "day": market.day,
        "revenue": round(market.total_revenue, 2),
        "cost": round(market.total_cost, 2),
        "profit": round(profit, 2),
        "units_sold_today": market.units_sold_today,
        "total_units_sold": market.total_units_sold,
        "avg_price": market.my_price,
        "inventory": market.my_inventory,
    })


@app.route("/pricing", methods=["POST"])
def set_pricing():
    data = request.get_json() or {}
    new_price = float(data.get("price", market.my_price))
    market.my_price = round(new_price, 2)
    market._log(f"调整售价为 ${market.my_price}")
    return jsonify({"price": market.my_price, "status": "ok"})


@app.route("/inventory", methods=["POST"])
def restock():
    data = request.get_json() or {}
    units = int(data.get("units", 100))
    cost = units * market.supplier_price
    market.my_inventory += units
    market.total_cost += cost
    market._log(f"采购{units}件, 成本${cost:.0f}")
    return jsonify({
        "units_added": units,
        "cost": round(cost, 2),
        "inventory": market.my_inventory,
    })


@app.route("/market-status")
def market_status():
    profit = market.total_revenue - market.total_cost
    return jsonify({
        "day": market.day,
        "supplier_price": market.supplier_price,
        "supplier_trend": market.supplier_trend,
        "competitor_price": market.competitor_avg_price,
        "competitor_count": market.competitor_count,
        "market_demand": market.market_demand,
        "my_price": market.my_price,
        "my_inventory": market.my_inventory,
        "ad_budget": market.ad_budget,
        "total_revenue": round(market.total_revenue, 2),
        "total_cost": round(market.total_cost, 2),
        "total_profit": round(profit, 2),
        "units_sold_today": market.units_sold_today,
        "total_units_sold": market.total_units_sold,
    })


@app.route("/tick", methods=["POST"])
def advance_day():
    """推进一天"""
    market.tick()
    return jsonify({"day": market.day, "status": "ok", "events": market.events[-3:]})


@app.route("/events")
def get_events():
    return jsonify({"events": market.events[-20:]})


@app.route("/reset", methods=["POST"])
def reset():
    global market
    market = Market()
    return jsonify({"status": "reset", "day": 0})


if __name__ == "__main__":
    print("🏪 电商模拟器启动: http://0.0.0.0:5800")
    print("   API: /market-status /daily-sales /supplier-price /competitor-price")
    print("   Action: /pricing /inventory /ad-spend /tick /reset")
    app.run(host="0.0.0.0", port=5800, debug=False)
