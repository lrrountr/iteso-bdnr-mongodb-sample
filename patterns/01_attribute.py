"""
Attribute pattern.

An online store where each category has its own specs, and shoppers can filter
by any of them (RAM >= 16, screen >= 15, weight <= 10...).

    python 01_attribute.py
"""
import random

from helpers import coll_size, db, explain_find, say, show, step, title

rng = random.Random(42)
pick, randint = rng.choice, rng.randint

title("Attribute pattern: filtering products by any spec")

step("Setup: 3,000 products, 6 categories, 17 different specs")

CATEGORIES = {
    "laptop": lambda: {"ram_gb": pick([8, 16, 32]), "storage_gb": pick([256, 512, 1024]),
                       "cpu": pick(["i5", "i7", "ryzen7"]), "screen_in": pick([13, 14, 15.6])},
    "phone":  lambda: {"ram_gb": pick([4, 8, 12]), "storage_gb": pick([64, 128, 256]),
                       "camera_mp": pick([12, 48, 108]), "battery_mah": pick([3000, 4500, 5000])},
    "tshirt": lambda: {"size": pick(["S", "M", "L", "XL"]), "color": pick(["black", "white", "red"]),
                       "material": pick(["cotton", "polyester"])},
    "book":   lambda: {"pages": randint(100, 900), "author": pick(["J. Doe", "A. Ruiz", "M. Chen"]),
                       "language": pick(["es", "en"])},
    "bike":   lambda: {"frame_size_cm": pick([48, 52, 56]), "gears": pick([1, 7, 21]),
                       "weight_kg": randint(8, 16)},
    "tv":     lambda: {"screen_in": pick([43, 55, 65]), "resolution": pick(["1080p", "4k"]),
                       "refresh_hz": pick([60, 120])},
}

products_fields = db.products_fields   # design A: one field per spec
products_attr = db.products_attr       # design B: list of {k, v}
products_fields.drop()
products_attr.drop()

field_docs, attr_docs = [], []
for i in range(1, 3001):
    ptype = pick(list(CATEGORIES))
    specs = CATEGORIES[ptype]()
    base = {"_id": i, "type": ptype, "name": f"{ptype} #{i}", "price": randint(10, 2000)}
    field_docs.append({**base, "specs": specs})
    attr_docs.append({**base, "specs": [{"k": k, "v": v} for k, v in specs.items()]})

# only 8 GB of RAM, but it has a 512 in another spec. We'll need this later.
trap = {"_id": 9999, "type": "laptop", "name": "Cheap Laptop", "price": 400}
field_docs.append({**trap, "specs": {"ram_gb": 8, "storage_gb": 512}})
attr_docs.append({**trap, "specs": [{"k": "ram_gb", "v": 8}, {"k": "storage_gb", "v": 512}]})

products_fields.insert_many(field_docs)
products_attr.insert_many(attr_docs)

show("Design A, one field per spec (products_fields)", products_fields.find_one({"type": "laptop"}))
show("Design B, specs as {k, v} pairs (products_attr)", products_attr.find_one({"type": "laptop"}))

step("Design A: searching a spec with no index")

q1 = {"specs.ram_gb": {"$gte": 16}}
show(f"find({q1}), plan", explain_find(products_fields, q1))

spec_names = sorted(d["_id"] for d in products_fields.aggregate([
    {"$project": {"names": {"$map": {"input": {"$objectToArray": "$specs"}, "in": "$$this.k"}}}},
    {"$unwind": "$names"},
    {"$group": {"_id": "$names"}},
]))
show("Spec names we have", f"{len(spec_names)}: {', '.join(spec_names)}")

say("Collection scan: all 3,001 documents read for one filter.")
say(f"To fix it with this design we'd need one index per spec, so {len(spec_names)} indexes.")
say("Each index takes memory and slows down every insert and update, and the limit")
say("is 64 per collection. Add a new category (drones, with max_flight_min) and you")
say("need more fields and more indexes.")

step("Design B: one compound index for all the specs")

products_attr.create_index([("specs.k", 1), ("specs.v", 1)])
say('products_attr.create_index([("specs.k", 1), ("specs.v", 1)])')
say("Every spec is stored under the same two field names, so this one index covers")
say("ram_gb, screen_in, weight_kg, and any spec we add next year.")

step("Common mistake: dot notation on the array")

wrong_q = {"specs.k": "ram_gb", "specs.v": {"$gte": 16}}
right_q = {"specs": {"$elemMatch": {"k": "ram_gb", "v": {"$gte": 16}}}}

wrong_count = products_attr.count_documents(wrong_q)
right_count = products_attr.count_documents(right_q)
show(f"find({wrong_q}), count", wrong_count)
show("Is the 8 GB Cheap Laptop in there?", products_attr.count_documents({**wrong_q, "_id": 9999}) == 1)
show("Products that shouldn't be there", wrong_count - right_count)

say("Each condition is matched against any element of the array, separately.")
say('Cheap Laptop has k = "ram_gb" in one element and v = 512 in another, so it matches.')
say("No error and no warning, just the wrong products.")

step("Fix: $elemMatch")

show(f"find({right_q}), count", right_count)
show("Is the Cheap Laptop in there?", products_attr.count_documents({**right_q, "_id": 9999}) == 1)
show("Plan", explain_find(products_attr, right_q))
say("$elemMatch checks k and v on the same element. The index is used and MongoDB")
say("only reads the documents it returns.")

two_specs = {"specs": {"$all": [
    {"$elemMatch": {"k": "ram_gb", "v": {"$gte": 16}}},
    {"$elemMatch": {"k": "screen_in", "v": {"$gte": 15}}},
]}}
show("Two specs at once (RAM >= 16 and screen >= 15) with $all, count",
     products_attr.count_documents(two_specs))
show("Plan", explain_find(products_attr, two_specs))
say("The index narrows things down by one spec, the second one is checked after")
say("fetching the document. That's why keysExamined is bigger than nReturned.")

step("Where the pattern hurts: sorting by one spec")


def ram_of(doc):
    return next((s["v"] for s in doc["specs"] if s["k"] == "ram_gb"), None)


wrong_sort = products_attr.find({"type": "laptop"}).sort("specs.v", -1).limit(5)
show("sort('specs.v', -1), RAM of the first 5 laptops", [ram_of(d) for d in wrong_sort])
say("Sorting on an array field uses the largest value of any element. Here that's")
say("usually storage_gb (1024), so the order has nothing to do with RAM.")

right_sort = products_attr.aggregate([
    {"$match": {"type": "laptop"}},
    {"$set": {"ram_gb": {"$first": {"$filter": {"input": "$specs",
                                                "cond": {"$eq": ["$$this.k", "ram_gb"]}}}}}},
    {"$sort": {"ram_gb.v": -1, "_id": 1}},
    {"$limit": 5},
])
show("Pull out the RAM spec with $filter, then sort", [ram_of(d) for d in right_sort])
say("That works, but the sort happens in memory, not with the index.")
say("If users sort by a field, keep it as a normal top-level field, like price.")

step("Another option: a wildcard index")

products_fields.create_index([("specs.$**", 1)])
say('products_fields.create_index([("specs.$**", 1)])   # on design A')
show(f"Plan for {q1}", explain_find(products_fields, q1))
show("Sizes", [coll_size(products_attr), coll_size(products_fields)])
say("Also one index, and queries keep the natural field names. The catch: a wildcard")
say("index only helps with one field per query, and it needs MongoDB 4.2+ (compound")
say("wildcard indexes need 7.0+). Also look at dataKB: design B is bigger because every")
say("spec repeats 'k' and 'v'. Either choice is fine in the lab if you explain why.")

step("Why Attribute and not another pattern")

say("Polymorphic lets different shapes live together, but it doesn't make 17 specs searchable.")
say("Subset is for big arrays where you show a few items. Our spec lists have 3 or 4.")
say("Extended Reference is about avoiding joins, and there's no join here.")
say("Bucket is for lots of small time-based documents, which this isn't.")
say("What we give up: $elemMatch in every query, no easy sort by a spec, harder")
say("validation, and slightly bigger documents.")

step("Lab 2")

say("Task A1 in Lab 2 uses this data (products_attr). Keep it, don't drop the database yet.")
