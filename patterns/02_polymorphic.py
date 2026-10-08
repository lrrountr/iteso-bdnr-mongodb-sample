"""
Polymorphic pattern.

The same store sells laptops, t-shirts and books. Each type has its own fields,
but the "Deals under $50" page and the search results list them together.

    python 02_polymorphic.py
"""
import random

from pymongo.errors import OperationFailure, WriteError

from helpers import db, explain_find, say, show, step, title

rng = random.Random(7)
pick, randint = rng.choice, rng.randint

title("Polymorphic pattern: different shapes in one collection")

step("Setup: 3,000 products stored two ways")

for name in ("laptops", "tshirts", "books", "products_poly"):
    db[name].drop()

MAKE = {
    "laptop": lambda i: {"name": f"Laptop {i}", "price": randint(300, 2500),
                         "ram_gb": pick([8, 16, 32]), "cpu": pick(["i5", "i7"])},
    "tshirt": lambda i: {"name": f"Tee {i}", "price": randint(8, 40),
                         "size": pick(["S", "M", "L"]), "color": pick(["black", "white"])},
    "book":   lambda i: {"name": f"Book {i}", "price": randint(10, 80),
                         "isbn": f"978-{100000 + i}", "pages": randint(100, 900)},
}
separate = {"laptops": [], "tshirts": [], "books": []}
poly = []
for i in range(1, 3001):
    ptype = pick(list(MAKE))
    fields = MAKE[ptype](i)
    separate[ptype + "s"].append({"_id": i, **fields})   # design A: a collection per type
    poly.append({"_id": i, "type": ptype, **fields})     # design B: one collection with a type field

for name, docs in separate.items():
    db[name].insert_many(docs)
    db[name].create_index("price")
products = db.products_poly
products.insert_many(poly)

show("Design A, one collection per type", {name: db[name].count_documents({}) for name in separate})
show("Design B, products_poly, three shapes side by side",
     [products.find_one({"type": t}) for t in ("laptop", "tshirt", "book")])

step("Deals page: the 10 cheapest products under $50, any type")

deals_separate = [
    {"$match": {"price": {"$lt": 50}}}, {"$set": {"type": "laptop"}},
    {"$unionWith": {"coll": "tshirts", "pipeline": [{"$match": {"price": {"$lt": 50}}}, {"$set": {"type": "tshirt"}}]}},
    {"$unionWith": {"coll": "books", "pipeline": [{"$match": {"price": {"$lt": 50}}}, {"$set": {"type": "book"}}]}},
    {"$sort": {"price": 1, "_id": 1}},
    {"$limit": 10},
]
a = list(db.laptops.aggregate(deals_separate))
show("Design A with $unionWith, first 3 results", a[:3])
pulled = next(db.laptops.aggregate(deals_separate[:4] + [{"$count": "n"}]))["n"]
show("Documents pulled in and sorted in memory to keep 10", pulled)
say("Every product under $50 from all three collections has to be read, merged and")
say("sorted before the $limit. We also have to make up the type field inside the")
say("query, and adding headphones means editing every query like this one.")

products.create_index("price")
products.create_index([("type", 1), ("price", 1)])
deals_q = {"price": {"$lt": 50}}
b = list(products.find(deals_q).sort([("price", 1), ("_id", 1)]).limit(10))
show("Design B, first 3 results", b[:3])
show("Plan", explain_find(products, deals_q, sort={"price": 1}, limit=10))
say("A plain find() on one collection. The price index is already in order, so")
say("MongoDB reads 10 entries and stops. New types show up without changing anything.")
show("Laptops under $1000, using the {type, price} index",
     explain_find(products, {"type": "laptop", "price": {"$lt": 1000}}))

step("App code that assumes every product has the same fields")

try:
    show("[f\"{d['name']} {d['ram_gb']}GB\" for d in deals]", [f"{d['name']} {d['ram_gb']}GB" for d in b[:4]])
except KeyError as e:
    show("[f\"{d['name']} {d['ram_gb']}GB\" for d in deals]", f"KeyError: {e}")


def render(d):
    if d["type"] == "laptop":
        return f"{d['name']}, {d['ram_gb']} GB RAM"
    if d["type"] == "tshirt":
        return f"{d['name']}, size {d['size']}"
    if d["type"] == "book":
        return f"{d['name']}, {d['pages']} pages"


show("Checking d['type'] first", [render(d) for d in b[:4]])
say("T-shirts don't have ram_gb, and in this kind of collection that's expected.")
say("The type field is how the application knows which fields to read.")

step("A unique index on a field only books have")

try:
    products.create_index("isbn", unique=True)
except OperationFailure as e:
    msg = e.details.get("errmsg", str(e))
    show('create_index("isbn", unique=True)', msg[msg.find("E11000"):])
say("Laptops and t-shirts have no isbn, so the index treats all of them as isbn: null,")
say("which means thousands of duplicates.")

products.create_index("isbn", unique=True, partialFilterExpression={"type": "book"})
say('Fix: create_index("isbn", unique=True, partialFilterExpression={"type": "book"})')
isbn = products.find_one({"type": "book"})["isbn"]
show("find({'isbn': ...}) without type", explain_find(products, {"isbn": isbn}))
show("find({'type': 'book', 'isbn': ...})", explain_find(products, {"type": "book", "isbn": isbn}))
say("The partial index only contains books. One catch: the query has to include")
say("type: 'book', otherwise MongoDB can't use the index.")

step("Without validation, anything gets in")

products.insert_one({"_id": 90001, "type": "laptop", "name": "Mystery laptop", "price": 999})
say("A laptop with no ram_gb and no cpu was inserted without complaint.")
products.delete_one({"_id": 90001})

db.command("collMod", "products_poly", validator={"$jsonSchema": {
    "bsonType": "object",
    "required": ["type", "name", "price"],
    "properties": {"price": {"bsonType": ["int", "double", "long"], "minimum": 0}},
    "oneOf": [
        {"properties": {"type": {"enum": ["laptop"]}}, "required": ["ram_gb", "cpu"]},
        {"properties": {"type": {"enum": ["tshirt"]}}, "required": ["size", "color"]},
        {"properties": {"type": {"enum": ["book"]}}, "required": ["isbn", "pages"]},
    ],
}})
say("Added a $jsonSchema validator with oneOf, one set of required fields per type.")
try:
    products.insert_one({"_id": 90002, "type": "laptop", "name": "Mystery laptop", "price": 999})
except WriteError as e:
    show("Same laptop again", f"rejected, document failed validation (code {e.code})")
products.insert_one({"_id": 90003, "type": "laptop", "name": "Valid laptop", "price": 999,
                     "ram_gb": 16, "cpu": "i7"})
say("A complete laptop is accepted.")
products.delete_one({"_id": 90003})

step("Why Polymorphic and not another pattern")

say("Separate collections are better when the types are never listed together,")
say("like invoices and products.")
say("Attribute is about searching many specs, not about where the shapes live.")
say("A real store would use both: products_poly with a specs list of {k, v}.")
say("Subset and Extended Reference deal with big arrays and joins, not this.")
say("Bucket is for grouping time-based data.")
say("What we give up: the app has to check the type, some indexes need to be partial,")
say("and validation is written per type.")

step("Lab 2")

say("Task A2 in Lab 2 uses this data (products_poly). Keep it, don't drop the database yet.")
