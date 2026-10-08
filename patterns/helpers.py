"""Connection and small utilities shared by the demo scripts."""
import os
from pprint import pformat

import bson
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
client = MongoClient(MONGO_URI)
db = client["patterns_class"]


def title(text):
    print(f"\n{text}\n{'=' * len(text)}")


def step(text):
    print(f"\n{text}\n{'-' * len(text)}")


def say(text=""):
    print("  " + text)


def show(label, value):
    print(f"  {label}:")
    text = value if isinstance(value, str) else pformat(value, sort_dicts=False, width=90)
    print("\n".join("      " + line for line in text.splitlines()))


def plan_summary(explain_output):
    """Pull the useful numbers out of an explain() result (find or aggregate)."""
    stages, totals = [], {"keys": 0, "docs": 0, "returned": None}

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for k, v in node.items():
                if k in ("rejectedPlans", "allPlansExecution"):
                    continue
                # the SBE engine adds lowercase internal stages, we only want the classic ones
                if k == "stage" and isinstance(v, str) and v.isupper() and v not in stages:
                    stages.append(v)
                elif k == "totalKeysExamined" and isinstance(v, int):
                    totals["keys"] = max(totals["keys"], v)
                elif k == "totalDocsExamined" and isinstance(v, int):
                    totals["docs"] = max(totals["docs"], v)
                elif k == "nReturned" and isinstance(v, int) and totals["returned"] is None:
                    totals["returned"] = v
                walk(v)

    walk(explain_output)
    return {"stages": " <- ".join(stages), "keysExamined": totals["keys"],
            "docsExamined": totals["docs"], "nReturned": totals["returned"]}


def explain_find(coll, filter, sort=None, limit=0, skip=0, hint=None):
    cmd = {"find": coll.name, "filter": filter}
    if hint:
        cmd["hint"] = hint
    if sort:
        cmd["sort"] = sort
    if limit:
        cmd["limit"] = limit
    if skip:
        cmd["skip"] = skip
    return plan_summary(coll.database.command("explain", cmd, verbosity="executionStats"))


def explain_aggregate(coll, pipeline):
    cmd = {"aggregate": coll.name, "pipeline": pipeline, "cursor": {}}
    return plan_summary(coll.database.command("explain", cmd, verbosity="executionStats"))


def coll_size(coll):
    s = next(coll.aggregate([{"$collStats": {"storageStats": {}}}]))["storageStats"]
    return {"collection": coll.name, "documents": s["count"],
            "dataKB": round(s["size"] / 1024), "indexKB": round(s["totalIndexSize"] / 1024),
            "indexes": s["nindexes"]}


def kb(doc):
    """Size of a document in BSON, the way MongoDB stores it."""
    return f"{len(bson.encode(doc)) / 1024:.1f} KB"
