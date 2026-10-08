"""
Extended Reference pattern.

The "My orders" page is opened all the time. Each order shows the customer's
name and city, plus the name, price and quantity of each item.

    python 04_extended_reference.py
"""
import random
import time
from datetime import datetime, timedelta

from helpers import db, explain_find, kb, say, show, step, title

rng = random.Random(11)
pick, randint = rng.choice, rng.randint

title("Extended Reference pattern: copy the few fields you display")

step("Setup: 50 customers, 200 products, 5,000 orders stored two ways")

for name in ("customers", "catalog", "orders_ref", "orders_ext", "orders_bad"):
    db[name].drop()
customers, catalog = db.customers, db.catalog
orders_ref, orders_ext = db.orders_ref, db.orders_ext

FIRST = ["Ana", "Luis", "Sofía", "Max", "Carla", "Diego", "Valeria", "Tomás", "Regina", "Iker"]
LAST = ["López", "García", "Hernández", "Martínez", "Ruiz", "Chen", "Pérez", "Torres"]
CITIES = ["Guadalajara", "Zapopan", "Tlaquepaque", "CDMX", "Monterrey"]

customer_docs = [{
    "_id": c, "name": f"{pick(FIRST)} {pick(LAST)}", "email": f"user{c}@mail.com",
    "city": pick(CITIES), "address": f"Calle {randint(1, 999)}", "phone": f"33-{randint(1000, 9999)}",
    "loyalty_points": randint(0, 5000),     # changes with every purchase
} for c in range(1, 51)]
product_docs = [{
    "_id": p, "name": f"Product {p}", "price": randint(10, 2000),
    "stock": randint(0, 500),               # changes with every sale
    "description": "Long marketing text. " * 20,
} for p in range(1, 201)]
customers.insert_many(customer_docs)
catalog.insert_many(product_docs)

ref_docs, ext_docs = [], []
for o in range(1, 5001):
    cust = pick(customer_docs)
    items = [(pick(product_docs), randint(1, 3)) for _ in range(randint(1, 4))]
    date = datetime(2025, 1, 1) + timedelta(minutes=o * 97)
    # design A: only ids
    ref_docs.append({"_id": o, "customer_id": cust["_id"], "date": date,
                     "items": [{"product_id": p["_id"], "qty": q} for p, q in items]})
    # design B: ids plus the fields the order card shows
    ext_docs.append({
        "_id": o, "date": date,
        "customer": {"customer_id": cust["_id"], "name": cust["name"], "city": cust["city"]},
        "shipping_address": cust["address"],
        "items": [{"product_id": p["_id"], "name": p["name"], "price": p["price"], "qty": q}
                  for p, q in items],
        "total": sum(p["price"] * q for p, q in items),
    })
orders_ref.insert_many(ref_docs)
orders_ext.insert_many(ext_docs)
orders_ref.create_index([("customer_id", 1), ("date", -1)])
orders_ext.create_index([("customer.customer_id", 1), ("date", -1)])

show("Design A, orders_ref (only ids)", orders_ref.find_one({"_id": 1}))
show("Design B, orders_ext (ids plus copied fields)", orders_ext.find_one({"_id": 1}))

step("My orders: the latest 10 orders of customer 7")

my_orders_ref = [
    {"$match": {"customer_id": 7}},
    {"$sort": {"date": -1}},
    {"$limit": 10},
    {"$lookup": {"from": "customers", "localField": "customer_id", "foreignField": "_id",
                 "as": "customer", "pipeline": [{"$project": {"name": 1, "city": 1}}]}},
    {"$lookup": {"from": "catalog", "localField": "items.product_id", "foreignField": "_id",
                 "as": "products", "pipeline": [{"$project": {"name": 1, "price": 1}}]}},
    {"$set": {
        "customer": {"$first": "$customer"},
        "items": {"$map": {"input": "$items", "as": "it", "in": {"$mergeObjects": [
            "$$it",
            {"$first": {"$filter": {"input": "$products", "cond": {"$eq": ["$$this._id", "$$it.product_id"]}}}},
        ]}}},
    }},
    {"$unset": ["products", "items._id"]},
]
show("Design A, two $lookups, first order", next(orders_ref.aggregate(my_orders_ref)))

my_orders_q = {"customer.customer_id": 7}
show("Design B, first order", orders_ext.find_one(my_orders_q, sort=[("date", -1)]))
show("Design B plan", explain_find(orders_ext, my_orders_q, sort={"date": -1}, limit=10))


def timed(fn, runs=300):
    start = time.perf_counter()
    for _ in range(runs):
        fn()
    return f"{(time.perf_counter() - start) * 1000 / runs:.2f} ms per page"


show("300 page loads, design A", timed(lambda: list(orders_ref.aggregate(my_orders_ref))))
show("300 page loads, design B", timed(lambda: list(orders_ext.find(my_orders_q).sort("date", -1).limit(10))))
say("Design A touches three collections and then stitches items and products back")
say("together. Since this is the page people open the most, that cost adds up.")
say("Design B is one index scan: 10 keys, 10 documents. We only copied what the page")
say("shows (no email, phone or description), and kept the ids in case we need more.")
show("The price we pay: bigger orders",
     f"orders_ref #1 is {kb(orders_ref.find_one({'_id': 1}))}, "
     f"orders_ext #1 is {kb(orders_ext.find_one({'_id': 1}))}")

step("Design A changes history")

current_price = {"$getField": {"field": "price", "input": {"$first": {"$filter": {
    "input": "$p", "cond": {"$eq": ["$$this._id", "$$it.product_id"]}}}}}}
order_total_ref = [
    {"$match": {"_id": 1}},
    {"$lookup": {"from": "catalog", "localField": "items.product_id", "foreignField": "_id", "as": "p"}},
    {"$project": {"total": {"$sum": {"$map": {"input": "$items", "as": "it",
                                              "in": {"$multiply": ["$$it.qty", current_price]}}}}}},
]
first_product = orders_ref.find_one({"_id": 1})["items"][0]["product_id"]
before = next(orders_ref.aggregate(order_total_ref))["total"]
catalog.update_one({"_id": first_product}, {"$mul": {"price": 0.5}})     # 50% off sale today
after = next(orders_ref.aggregate(order_total_ref))["total"]
show(f"Order #1 total in design A, before and after a sale on product {first_product}",
     f"{before} before, {after} after")
show("Order #1 total in design B", orders_ext.find_one({"_id": 1})["total"])
say("The customer paid the old price. With only ids, the order looks up today's")
say("price and the old total quietly changes. So copying the price isn't only about")
say("speed: it's a record of what was paid, and it's the correct data.")
catalog.update_one({"_id": first_product}, {"$mul": {"price": 2}})       # end the sale

step("Copying fields that change all the time")

orders_ext.aggregate([
    {"$set": {"customer.loyalty_points": 0, "items": {"$map": {
        "input": "$items", "in": {"$mergeObjects": ["$$this", {"stock": 0}]}}}}},
    {"$out": "orders_bad"},
])
orders_bad = db.orders_bad
orders_bad.create_index("items.product_id")
orders_bad.create_index("customer.customer_id")
sold = pick(product_docs)["_id"]
buyer = 7
# one sale: one product, one customer
r1 = orders_bad.update_many({"items.product_id": sold}, {"$inc": {"items.$[i].stock": -1}},
                            array_filters=[{"i.product_id": sold}])
r2 = orders_bad.update_many({"customer.customer_id": buyer}, {"$inc": {"customer.loyalty_points": 10}})
show("Orders rewritten for a single sale, if stock and points are copied",
     r1.modified_count + r2.modified_count)
say("Stock and loyalty points change with every sale, so every copy has to be")
say("rewritten each time. One purchase rewrites more than a hundred old orders.")
say("Copy fields that are read a lot and rarely change: names, cities, titles.")
orders_bad.drop()

step("Syncing a copy that should stay as it was")

orders_ext.aggregate([{"$out": "orders_bad"}])
orders_bad = db.orders_bad
orders_bad.update_many({"items.product_id": first_product},
                       {"$set": {"items.$[i].price": 1}}, array_filters=[{"i.product_id": first_product}])
broken = orders_bad.count_documents({"$expr": {"$ne": ["$total", {"$sum": {"$map": {
    "input": "$items", "in": {"$multiply": ["$$this.price", "$$this.qty"]}}}}]}})
show("Orders whose items no longer add up to the total after a price update", broken)
say("Prices in old orders, receipts and shipping addresses describe something that")
say("already happened. For each copied field, decide whether it should follow the")
say("original or stay frozen.")
orders_bad.drop()

step("A customer changes their name")

new_name = customers.find_one({"_id": 7})["name"] + " Ruiz"
customers.update_one({"_id": 7}, {"$set": {"name": new_name}})
r = orders_ext.update_many({"customer.customer_id": 7}, {"$set": {"customer.name": new_name}})
show("update_many({'customer.customer_id': 7}, {'$set': {'customer.name': ...}})",
     f"matched {r.matched_count}, modified {r.modified_count}")
say("Names change rarely, so we don't pay this often, and the customer.customer_id")
say("index finds the copies without scanning 5,000 orders. It's not atomic across")
say("documents, so for a moment some orders show the old name. That's fine here.")

step("Checking for copies that are out of date")

customers.update_one({"_id": 8}, {"$set": {"name": "Someone Renamed"}})   # forgot to update the orders
stale = list(orders_ext.aggregate([
    {"$lookup": {"from": "customers", "localField": "customer.customer_id", "foreignField": "_id",
                 "as": "src", "pipeline": [{"$project": {"name": 1}}]}},
    {"$match": {"$expr": {"$ne": ["$customer.name", {"$first": "$src.name"}]}}},
    {"$group": {"_id": "$customer.customer_id", "stale_orders": {"$sum": 1}}},
]))
show("Customers whose name is out of date in their orders", stale)
say("Once you duplicate data, keeping it consistent is your job. A query like this")
say("can run every night, and your design doc should list every place a field is copied.")

step("Why Extended Reference and not another pattern")

say("References with $lookup keep one copy of everything. That's fine for queries")
say("that run rarely or with little traffic.")
say("Embedding the whole customer would copy email, phone, points and more into")
say("5,000 orders: big documents and constant updates.")
say("Subset is for a few documents out of a long list. Here we need a few fields")
say("from one document.")
say("Attribute, Bucket and Polymorphic solve other problems (searchable specs,")
say("time series, different shapes).")
say("What we give up: bigger orders, an update_many when a copied field changes,")
say("and checking for stale copies.")

step("Lab 2")

say("Task A4 in Lab 2 uses this data (customers and orders_ext). Keep it, don't drop the database yet.")
