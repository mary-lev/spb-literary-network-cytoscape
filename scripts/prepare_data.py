"""Prepare node and edge tables for Cytoscape from the SPbLitGuide dataset.

Steps
1. Download events.csv and persons.csv from Zenodo (DOI 10.5281/zenodo.13753154)
   and the Louvain community assignments published with the JCLS article
   (github.com/mary-lev/literary_communities).
2. Rebuild the person-to-person co-participation network exactly as in the
   paper: for an event with n participants every pair gets weight 1/(n-1),
   summed over all shared events.
3. Print the global statistics and compare them with the paper.
4. Keep the 50 highest-degree members of Communities 0, 3 and 17 and the
   edges among them; write data/nodes.csv and data/edges.csv.
"""
import ast
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

ZENODO = "https://zenodo.org/records/13753154/files/{}?download=1"
COMMUNITY_JSON = ("https://raw.githubusercontent.com/mary-lev/literary_communities/"
                  "main/public/community_data.json")

COMMUNITIES = {
    0: "Experimental / avant-garde poetry",
    3: "Literary traditionalism / thick journals",
    17: "New prose / Petersburg Fundamentalists",
}
TOP_N = 50
PAPER = {"nodes": 10656, "edges": 106127, "components": 387, "giant": 9621}


def download(url, dest):
    if dest.exists():
        return
    print(f"downloading {url} -> {dest.name}")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)


def build_full_graph(events):
    weight = defaultdict(float)
    shared = defaultdict(int)
    for raw in events["people_list"].dropna():
        people = sorted(set(int(p) for p in ast.literal_eval(raw)))
        n = len(people)
        if n < 2:
            continue
        for a, b in itertools.combinations(people, 2):
            weight[(a, b)] += 1.0 / (n - 1)
            shared[(a, b)] += 1
    g = nx.Graph()
    for (a, b), w in weight.items():
        g.add_edge(a, b, weight=round(w, 4), shared_events=shared[(a, b)])
    return g


def main():
    csv_kwargs = {}
    if sys.version_info >= (3, 8):
        import csv
        csv.field_size_limit(sys.maxsize)
    for name in ("events.csv", "persons.csv"):
        download(ZENODO.format(name), RAW / name)
    download(COMMUNITY_JSON, RAW / "community_data.json")

    events = pd.read_csv(RAW / "events.csv", engine="python", **csv_kwargs)
    persons = pd.read_csv(RAW / "persons.csv").set_index("id")
    assignments = {int(k): v for k, v in
                   json.load(open(RAW / "community_data.json"))["community_assignments"].items()}

    g = build_full_graph(events)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    stats = {"nodes": g.number_of_nodes(), "edges": g.number_of_edges(),
             "components": len(comps), "giant": len(comps[0])}
    print("full network (rebuilt) vs paper:")
    for k, v in stats.items():
        print(f"  {k:11s} {v:>7d}   paper {PAPER[k]:>7d}")

    degree = dict(g.degree())
    rows = []
    for cid, cname in COMMUNITIES.items():
        members = [p for p, c in assignments.items() if c == cid and p in g]
        members.sort(key=lambda p: degree[p], reverse=True)
        print(f"community {cid}: {len(members)} members, keeping top {TOP_N}")
        for p in members[:TOP_N]:
            per = persons.loc[p]
            rows.append({
                "id": p,
                "label": per["transliterated_name"].strip() if isinstance(per.get("transliterated_name"), str) else str(p),
                "name_cyrillic": per["name"],
                "community_id": cid,
                "community": cname,
                "degree": degree[p],
                "viaf_id": per.get("viaf_id", ""),
                "wikidata_id": per.get("wikidata_id", ""),
            })
    nodes = pd.DataFrame(rows)
    nodes["label"] = nodes["label"].str.replace(r"\s+", " ", regex=True)
    keep = set(nodes["id"])
    sub = g.subgraph(keep)
    edges = pd.DataFrame(
        [{"source": a, "target": b, "weight": d["weight"], "shared_events": d["shared_events"]}
         for a, b, d in sub.edges(data=True)]
    ).sort_values("weight", ascending=False)
    print(f"subgraph: {sub.number_of_nodes()} nodes, {sub.number_of_edges()} edges")
    nodes.to_csv(ROOT / "data" / "nodes.csv", index=False)
    edges.to_csv(ROOT / "data" / "edges.csv", index=False)
    print("sample nodes:\n", nodes.head(3).to_string())
    print("sample edges:\n", edges.head(3).to_string())


if __name__ == "__main__":
    main()
