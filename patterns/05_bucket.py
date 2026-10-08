"""
Bucket pattern.

A smartwatch sends the step count every minute. The app shows "steps today"
and an hourly chart. Nobody asks for one specific minute.

    python 05_bucket.py
"""
import random
from datetime import datetime, timedelta

from pymongo.errors import DuplicateKeyError

from helpers import coll_size, db, explain_aggregate, kb, say, show, step, title

rng = random.Random(5)

title("Bucket pattern: grouping lots of small time-based documents")

step("Setup: 3 users, 7 days, one reading per minute")

for name in ("steps_naive", "steps_bucket", "steps_ts"):
    db[name].drop()
steps_naive, steps_bucket = db.steps_naive, db.steps_bucket

USERS = ["ana", "luis", "sofi"]
DAY0 = datetime(2026, 10, 1)


def steps_at(ts):
    if ts.hour < 7 or ts.hour >= 23:
        return 0  # asleep
    return rng.choice([0, 0, 5, 20, 40, 80, 110])


naive_docs, buckets = [], {}
for user in USERS:
    for minute in range(7 * 24 * 60):
        ts = DAY0 + timedelta(minutes=minute)
        s = steps_at(ts)
        naive_docs.append({"user": user, "ts": ts, "steps": s})
        start = ts.replace(minute=0)
        b = buckets.setdefault((user, start), {"user": user, "start": start, "count": 0,
                                               "total_steps": 0, "readings": []})
        b["readings"].append({"m": ts.minute, "steps": s})
        b["count"] += 1
        b["total_steps"] += s

steps_naive.insert_many(naive_docs)
steps_naive.create_index([("user", 1), ("ts", 1)])
steps_bucket.insert_many(list(buckets.values()))
steps_bucket.create_index([("user", 1), ("start", 1)], unique=True)

show("Design A, steps_naive, one document per minute", steps_naive.find_one({}, {"_id": 0}))
sample = steps_bucket.find_one({"start": DAY0.replace(hour=9)}, {"_id": 0})
sample["readings"] = sample["readings"][:3] + ["... 57 more"]
show("Design B, steps_bucket, one document per user per hour", sample)

step("Design A: one document per reading")

show("Storage", [coll_size(steps_naive), coll_size(steps_bucket)])
say("With 10,000 users for a year:")
say(f"  one document per minute: {10_000 * 525_600:>15,}")
say(f"  one document per hour:   {10_000 * 8_760:>15,}  (60 times fewer)")
say("Each document has its own _id, field names and index entries, all to store one")
say("small number. Compare indexKB. And any question about a day has to read 1,440")
say("documents.")

step("Steps today for ana (day 7)")

day = DAY0 + timedelta(days=6)
next_day = day + timedelta(days=1)

q_naive = [{"$match": {"user": "ana", "ts": {"$gte": day, "$lt": next_day}}},
           {"$group": {"_id": "$user", "steps_today": {"$sum": "$steps"}}}]
q_bucket_unwind = [{"$match": {"user": "ana", "start": {"$gte": day, "$lt": next_day}}},
                   {"$unwind": "$readings"},
                   {"$group": {"_id": "$user", "steps_today": {"$sum": "$readings.steps"}}}]
q_bucket = [{"$match": {"user": "ana", "start": {"$gte": day, "$lt": next_day}}},
            {"$group": {"_id": "$user", "steps_today": {"$sum": "$total_steps"}}}]

show("Design A, result", list(steps_naive.aggregate(q_naive)))
show("Design A, plan", explain_aggregate(steps_naive, q_naive))
show("Design B with $unwind on the readings, result", list(steps_bucket.aggregate(q_bucket_unwind)))
say("Same answer, but $unwind turns the 24 buckets back into 1,440 documents in")
say("memory. We built the buckets and then ignored their totals.")
show("Design B summing total_steps, result", list(steps_bucket.aggregate(q_bucket)))
show("Design B, plan", explain_aggregate(steps_bucket, q_bucket))
say("Same answer from 24 documents instead of 1,440, and the arrays are never opened.")
say("The total is kept up to date when we write, so reading it is cheap.")

chart = list(steps_bucket.find({"user": "ana", "start": {"$gte": day, "$lt": next_day}},
                               {"_id": 0, "start": 1, "total_steps": 1}).sort("start", 1))
show("Hourly chart from a plain find(), first 12 hours",
     [f"{b['start']:%H}h: {b['total_steps']}" for b in chart[:12]])

step("Writing a new reading")

new_ts = DAY0 + timedelta(days=7, minutes=1)    # new hour, no bucket for it yet


def add_reading(user, ts, s):
    steps_bucket.update_one(
        {"user": user, "start": ts.replace(minute=0, second=0)},
        {"$push": {"readings": {"m": ts.minute, "steps": s}},
         "$inc": {"count": 1, "total_steps": s}},
        upsert=True,
    )


add_reading("ana", new_ts, 0)
add_reading("ana", new_ts + timedelta(minutes=1), 3)
show("Bucket after two readings",
     steps_bucket.find_one({"user": "ana", "start": new_ts.replace(minute=0)}, {"_id": 0}))
say("The first upsert created the bucket and the second one added to it. One atomic")
say("update per reading, and a bucket never holds more than 60 readings because")
say("each one covers a single hour.")

step("Picking the wrong bucket size")

day_bucket = {"user": "ana", "start": day, "readings": [{"s": i, "steps": 1} for i in range(86_400)]}
hour_bucket = steps_bucket.find_one({"user": "ana", "start": day.replace(hour=9)})
show("One bucket per day, one reading per second", kb(day_bucket) + " (86,400 readings)")
show("One bucket per hour, one reading per minute", kb(hour_bucket) + " (60 readings)")
say("With day buckets, every new reading means working with a document of several")
say("MB, and drawing one hour loads the whole day. Going too small doesn't help")
say("either: a bucket per minute saves almost nothing. Size the bucket to match your")
say("queries (an hourly chart, hourly buckets) and know the maximum it can hold.")

step("No unique index, duplicate buckets")

db.steps_dup.drop()
steps_bucket.aggregate([{"$match": {"user": "ana", "start": {"$gte": day, "$lt": next_day}}},
                        {"$out": "steps_dup"}])
dup = db.steps_dup                    # same data, but no unique index
twin = dup.find_one({"start": day.replace(hour=9)}, {"_id": 0})
dup.insert_one(twin)                  # two writers upserting a new bucket at the same time can do this
show("Steps today with one duplicate bucket", list(dup.aggregate(q_bucket)))
say("If two upserts for a new hour arrive at the same moment, both can insert a")
say("bucket. Nothing fails, the total is just counted twice.")
try:
    steps_bucket.insert_one(twin)
except DuplicateKeyError:
    show("Same insert with the unique index on {user, start}", "DuplicateKeyError")
say("With the unique index there can only be one bucket per user per hour.")
dup.drop()

step("Fixing one reading and forgetting the total")

target = {"user": "ana", "start": day.replace(hour=9)}
steps_bucket.update_one(target, {"$set": {"readings.$[r].steps": 999}}, array_filters=[{"r.m": 37}])
b = steps_bucket.find_one(target)
show("total_steps vs the actual sum of readings, after an arrayFilters update",
     f"{b['total_steps']} vs {sum(r['steps'] for r in b['readings'])}")
say("total_steps is calculated from the readings, so changing a reading left it wrong.")

steps_bucket.update_one(target, [
    {"$set": {"readings": {"$map": {"input": "$readings", "in": {"$cond": [
        {"$eq": ["$$this.m", 37]}, {"m": 37, "steps": 15}, "$$this"]}}}}},
    {"$set": {"total_steps": {"$sum": "$readings.steps"}}},
])
b = steps_bucket.find_one(target)
show("After a pipeline update that changes the reading and recalculates the total",
     f"{b['total_steps']} vs {sum(r['steps'] for r in b['readings'])}")
say("Both changes happen in a single update to a single document, so they always match.")
say("Still, editing one reading is clearly more work than in design A.")

step("Another option: time series collections")

db.create_collection("steps_ts", timeseries={"timeField": "ts", "metaField": "user", "granularity": "minutes"})
db.steps_ts.insert_many([{k: v for k, v in d.items() if k != "_id"} for d in naive_docs])
show("Steps today from a time series collection (same query as design A)",
     list(db.steps_ts.aggregate(q_naive)))
ts_stats = next(db.steps_ts.aggregate([{"$collStats": {"storageStats": {}}}]))["storageStats"]
show("Time series storage", {
    "readings": ts_stats["timeseries"]["numMeasurementsCommitted"],
    "internal buckets": ts_stats["timeseries"]["bucketCount"],
    "dataKB": round(ts_stats["size"] / 1024),
    "steps_naive dataKB, for comparison": coll_size(steps_naive)["dataKB"],
})
say("You insert one document per reading and MongoDB does the bucketing (and")
say("compression) itself. For sensor data in a real project, use this. Doing it by")
say("hand is still worth learning, and the idea works for data that isn't about")
say("time too, like reviews in pages of 50.")

step("Why Bucket and not another pattern")

say("One document per reading means a huge number of documents and index entries")
say("for very little data.")
say("Embedding the readings in the user document gives an array that never stops")
say("growing and eventually hits 16 MB.")
say("Subset keeps only the newest few items. Here we need all of the data, grouped")
say("by time.")
say("Attribute, Extended Reference and Polymorphic are about specs, joins and")
say("shapes, not this.")
say("What we give up: editing a single reading is harder, we have to choose a bucket")
say("size, and we need the unique index.")

step("Lab 2")

say("Task A5 in Lab 2 uses this data (steps_bucket). Keep it, don't drop the database yet.")
