"""Update seed tools in main.py for multi-product support"""
content = open('/home/suoyi/cognitive-embryo/main.py').read()

# Update restock_inventory to support product_id
old_restock = '''        ("restock_inventory", "采购补货",
import urllib.request, json
def restock_inventory(units: int):
    data = json.dumps({"units": units}).encode()
    req = urllib.request.Request("http://127.0.0.1:5800/inventory", data=data, headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.dumps(json.loads(r.read()), ensure_ascii=False)''',
         {"name": "restock_inventory", "description": "采购补货，增加库存",
          "parameters": {"type": "object", "properties": {"units": {"type": "integer", "description": "采购数量"}}, "required": ["units"]}}),'''

new_restock = '''        ("restock_inventory", "采购补货",
import urllib.request, json
def restock_inventory(units: int, product_id: str = "a"):
    data = json.dumps({"units": units, "product_id": product_id}).encode()
    req = urllib.request.Request("http://127.0.0.1:5800/inventory", data=data, headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.dumps(json.loads(r.read()), ensure_ascii=False)''',
         {"name": "restock_inventory", "description": "采购补货，增加库存",
          "parameters": {"type": "object", "properties": {"units": {"type": "integer", "description": "采购数量"}, "product_id": {"type": "string", "description": "商品ID (a/b/c/d)，默认a"}}, "required": ["units"]}}),'''

content = content.replace(old_restock, new_restock)

# Add new tools before advance_day
old_advance = '''        ("advance_day", "推进到下一天（触发市场波动和销售结算）","""

new_advance = '''        ("get_products_list", "获取所有商品列表及状态",
import urllib.request, json
def get_products_list():
    with urllib.request.urlopen("http://127.0.0.1:5800/products") as r:
        return json.dumps(json.loads(r.read()), ensure_ascii=False)''',
         {"name": "get_products_list", "description": "获取所有4种商品(a电子/b服装/c食品/d家电)的售价/库存/利润",
          "parameters": {"type": "object", "properties": {}, "required": []}}),

        ("product_pricing", "设置某商品售价",
import urllib.request, json
def product_pricing(product_id: str, price: float):
    data = json.dumps({"product_id": product_id, "price": price}).encode()
    req = urllib.request.Request("http://127.0.0.1:5800/product-pricing", data=data, headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.dumps(json.loads(r.read()), ensure_ascii=False)''',
         {"name": "product_pricing", "description": "设置某商品售价",
          "parameters": {"type": "object", "properties": {"product_id": {"type": "string", "description": "商品ID (a/b/c/d)"}, "price": {"type": "number", "description": "新售价"}}, "required": ["product_id", "price"]}}),

        ("get_competitors_info", "获取各商品的竞品信息",
import urllib.request, json
def get_competitors_info():
    with urllib.request.urlopen("http://127.0.0.1:5800/competitors") as r:
        return json.dumps(json.loads(r.read()), ensure_ascii=False)''',
         {"name": "get_competitors_info", "description": "获取各商品的竞品价格和市场信息",
          "parameters": {"type": "object", "properties": {}, "required": []}}),

        ("advance_day", "推进到下一天（触发市场波动和销售结算）","""

content = content.replace(old_advance, new_advance)

open('/home/suoyi/cognitive-embryo/main.py', 'w').write(content)
print("OK")
