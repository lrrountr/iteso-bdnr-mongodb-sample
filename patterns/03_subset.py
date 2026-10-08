"""
Subset pattern.

The product page is the most visited page in the store. It shows the product,
its average rating and the 3 newest reviews. A product can have thousands of
reviews, and "See all reviews" is rarely clicked.

    python 03_subset.py
"""
import random
from datetime import datetime, timedelta

import bson

from helpers import coll_size, db, explain_find, kb, say, show, step, title

rng = random.Random(3)
pick, randint = rng.choice, rng.randint

title("Subset pattern: embed only what the page shows")

step("Setup: 20 products with 500 to 3,000 reviews each")

for name in ("products_naive", "products_subset", "products_subset_tmp", "reviews"):
    db[name].drop()
products_naive, products_subset, reviews = db.products_naive, db.products_subset, db.reviews

USERS = ["ana", "luis", "sofi", "max", "carla", "diego", "vale", "tomas"]
PHRASES = ["Works great, fast shipping.", "Not what I expected, but OK.", "Excellent quality for the price.",
           "Stopped working after a month.", "Would buy again!", "Good, but the manual is confusing."]


def without_product_id(review):
    return {k: v for k, v in review.items() if k != "product_id"}


review_id = 1
naive_docs, subset_docs, review_docs = [], [], []
for p in range(1, 21):
    n = 3000 if p == 1 else randint(500, 3000)
    mine = []
    for i in range(n):
        mine.append({
            "_id": review_id, "product_id": p, "user": pick(USERS), "stars": pick([5, 5, 5, 4, 4, 3, 2, 1]),
            "text": " ".join(pick(PHRASES) for _ in range(3)),
            "date": datetime(2025, 1, 1) + timedelta(days=randint(0, 640), seconds=i),
        })
        review_id += 1
    mine.sort(key=lambda r: r["date"], reverse=True)
    product = {"_id": p, "name": f"Product {p}", "price": randint(10, 2000)}

    # design A: every review inside the product
    naive_docs.append({**product, "reviews": [without_product_id(r) for r in mine]})

    # design B: the 3 newest inside the product, all of them in the reviews collection
    subset_docs.append({
        **product,
        "review_count": n,
        "rating_sum": sum(r["stars"] for r in mine),
        "top_reviews": [without_product_id(r) for r in mine[:3]],
    })
    review_docs.extend(mine)

products_naive.insert_many(naive_docs)
products_subset.insert_many(subset_docs)
reviews.insert_many(review_docs)
reviews.create_index([("product_id", 1), ("date", -1)])

say("products_naive:  each product has all of its reviews embedded")
say("products_subset: each product has its 3 newest reviews, review_count and rating_sum")
say("reviews:         one document per review, this is where the real data lives")
show("products_subset, product 1", products_subset.find_one({"_id": 1}))

step("Design A: embedding every review")

big_doc = products_naive.find_one({"_id": 1})
small_doc = products_subset.find_one({"_id": 1})
show("Product 1 with all reviews embedded", f"{kb(big_doc)} ({len(big_doc['reviews'])} reviews)")
show("Product 1 with the subset", kb(small_doc))
show("Collections", [coll_size(products_naive), coll_size(products_subset)])
per_review = len(bson.encode(big_doc)) / len(big_doc["reviews"])
show("Roughly how many reviews fit before the 16 MB limit", int(16 * 1024 * 1024 / per_review))
say(f"The page shows 3 reviews, but every visit loads {kb(big_doc)} into memory.")
say("MongoDB caches whole documents, so the cache fills up with reviews nobody")
say("reads and other data gets pushed out. That slows everything down long")
say("before a product gets anywhere near 16 MB.")

step("\"Can't I just project $slice: 3?\"")

sliced = products_naive.find_one({"_id": 1}, {"name": 1, "reviews": {"$slice": 3}})
show('find_one({"_id": 1}, {"reviews": {"$slice": 3}}), size sent to the client', kb(sliced))
say("Less goes over the network, but the server still had to read the whole")
say(f"{kb(big_doc)} document to cut 3 reviews out of it. The projection hides")
say("the problem, it doesn't fix it.")

step("Design B: the product page is one small read")

page = products_subset.find_one({"_id": 1}, {
    "name": 1, "price": 1, "review_count": 1, "top_reviews": 1,
    "avg_rating": {"$round": [{"$divide": ["$rating_sum", "$review_count"]}, 2]},
})
show("Product page", page)
say(f"Everything the page needs is in a {kb(small_doc)} document. The average is")
say("calculated from rating_sum / review_count when we read it.")

show("\"See all reviews\", page 2, plan",
     explain_find(reviews, {"product_id": 1}, sort={"date": -1}, skip=10, limit=10))
say("The full list is a separate query, but it's rare, and the {product_id, date}")
say("index returns the reviews already sorted.")

step("Adding a review with a plain $push")

tmp = db.products_subset_tmp
products_subset.aggregate([{"$match": {"_id": 2}}, {"$out": "products_subset_tmp"}])
for i in range(5):
    tmp.update_one({"_id": 2}, {"$push": {"top_reviews": {
        "_id": 900000 + i, "user": "max", "stars": 4, "text": f"push {i}", "date": datetime.now()}}})
show("top_reviews length after 5 pushes", len(tmp.find_one({"_id": 2})["top_reviews"]))
say("The subset keeps growing, and little by little we're back to design A.")
tmp.drop()

step("Fix: insert into reviews, then $push with $sort and $slice")

new_review = {"_id": review_id, "product_id": 1, "user": "max", "stars": 1,
              "text": "Arrived broken.", "date": datetime.now()}
reviews.insert_one(new_review)
products_subset.update_one({"_id": 1}, {
    "$push": {"top_reviews": {"$each": [without_product_id(new_review)],
                              "$sort": {"date": -1}, "$slice": 3}},
    "$inc": {"review_count": 1, "rating_sum": new_review["stars"]},
})
after = products_subset.find_one({"_id": 1})
show("top_reviews now", [f"{r['user']} {r['stars']}* {r['date']:%Y-%m-%d}" for r in after["top_reviews"]])
show("review_count / rating_sum", f"{after['review_count']} / {after['rating_sum']}")
say("$slice keeps only the newest 3, and $inc updates the counters without reading")
say("the document first. It is two writes, though: if the second one fails, the")
say("page shows an old preview for a while. For a preview that's acceptable, if")
say("it isn't for you, use a transaction.")

step("Storing the average instead of sum and count")

old_count, old_sum = after["review_count"] - 1, after["rating_sum"] - 1
old_avg = old_sum / old_count
show(f"Average before the new review ({old_count} reviews)", f"{old_avg:.3f}")
show("Updating it as (old average + new stars) / 2", f"{(old_avg + 1) / 2:.3f}")
show("rating_sum / review_count", f"{after['rating_sum'] / after['review_count']:.3f}")
say("An average doesn't remember how many reviews it came from, so you can't")
say("update it correctly. One 1-star review shouldn't cut the rating of 3,000")
say("reviews in half. Keep the sum and the count, and calculate the average.")

step("Deleting a top review with only $pull")

victim = after["top_reviews"][0]
products_subset.aggregate([{"$match": {"_id": 1}}, {"$out": "products_subset_tmp"}])
tmp.update_one({"_id": 1}, {"$pull": {"top_reviews": {"_id": victim["_id"]}}})
show("top_reviews length after $pull", len(tmp.find_one({"_id": 1})["top_reviews"]))
say("$slice removes extra items but never brings any back. Now the page shows 2")
say("reviews, and each delete makes it worse.")
tmp.drop()

reviews.delete_one({"_id": victim["_id"]})
new_top = list(reviews.find({"product_id": 1}, {"product_id": 0}).sort("date", -1).limit(3))
products_subset.update_one({"_id": 1}, {
    "$set": {"top_reviews": new_top},
    "$inc": {"review_count": -1, "rating_sum": -victim["stars"]},
})
show("Delete from reviews, then rebuild top_reviews from it",
     [f"{r['user']} {r['stars']}*" for r in products_subset.find_one({"_id": 1})["top_reviews"]])
say("The reviews collection has the real data. top_reviews is just a copy of the")
say("first few, so after a delete we rebuild it from reviews.")

step("Why Subset and not another pattern")

say("Embedding everything doesn't scale, as we saw: big documents and a wasted cache.")
say("Only referencing works, but the busiest page would need two queries every time.")
say("Bucket could group reviews into pages of 50. That's worth it if people page")
say("through reviews a lot, and here they don't.")
say("Extended Reference copies a few fields from one related document. Here we need")
say("a few whole documents out of a long list (each embedded review is a small")
say("extended reference itself, though).")
say("What we give up: reviews stored twice, two writes per change, and rebuilding")
say("the subset when one is deleted.")

step("Lab 2")

say("Task A3 in Lab 2 uses this data (reviews). Keep it, don't drop the database yet.")
