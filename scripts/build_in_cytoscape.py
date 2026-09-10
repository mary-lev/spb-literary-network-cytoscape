"""Drive Cytoscape 3.10 through CyREST (py4cytoscape) to reproduce the
tutorial steps on data/nodes.csv and data/edges.csv:

  * import the edge list and node attributes,
  * apply a visual style (colour by community, size by degree, edge width by
    weight, transliterated labels),
  * lay the network out,
  * Option 1: export a static PNG,
  * Option 2: export the network as Cytoscape.js JSON (.cyjs) and the style
    as "Style for cytoscape.js" (.json),
  * save the session (.cys).

Cytoscape must be running (GUI, possibly under Xvfb) with CyREST on port 1234.
"""
from pathlib import Path

import pandas as pd
import py4cytoscape as p4c

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cytoscape"
OUT.mkdir(exist_ok=True)

STYLE = "SPbLitCommunities"
COLOURS = {"0": "#D55E00", "3": "#0072B2", "17": "#009E73"}  # Okabe-Ito, colour-blind safe

p4c.cytoscape_ping()
print("Cytoscape", p4c.cytoscape_version_info()["cytoscapeVersion"])
p4c.close_session(False)

nodes = pd.read_csv(ROOT / "data" / "nodes.csv")
edges = pd.read_csv(ROOT / "data" / "edges.csv")
nodes["id"] = nodes["id"].astype(str)
nodes["community_id"] = nodes["community_id"].astype(str)  # discrete mapping wants strings
edges["source"] = edges["source"].astype(str)
edges["target"] = edges["target"].astype(str)
edges["interaction"] = "co-participation"

suid = p4c.create_network_from_data_frames(
    nodes, edges, title="SPbLitGuide communities 0, 3, 17",
    collection="SPbLitGuide 1999-2019")
print("network SUID", suid, p4c.get_node_count(), "nodes",
      p4c.get_edge_count(), "edges")

# --- style -----------------------------------------------------------------
p4c.create_visual_style(STYLE, defaults={
    "NODE_SHAPE": "ELLIPSE",
    "NODE_BORDER_WIDTH": 1.0,
    "NODE_BORDER_PAINT": "#FFFFFF",
    "NODE_LABEL_FONT_SIZE": 10,
    "NODE_LABEL_COLOR": "#222222",
    "EDGE_STROKE_UNSELECTED_PAINT": "#9A9A9A",
    "EDGE_TRANSPARENCY": 255,
    "NETWORK_BACKGROUND_PAINT": "#FFFFFF",
})
p4c.set_node_label_mapping("label", style_name=STYLE)
p4c.set_node_color_mapping("community_id", list(COLOURS), list(COLOURS.values()),
                           mapping_type="d", style_name=STYLE)
# NODE_SIZE (locked width/height) is not written to the cytoscape.js style
# export, so unlock the dimensions and map width and height separately.
p4c.lock_node_dimensions(False, style_name=STYLE)
for setter in (p4c.set_node_width_mapping, p4c.set_node_height_mapping):
    setter("degree", [int(nodes.degree.min()), int(nodes.degree.max())],
           [18, 70], mapping_type="c", style_name=STYLE)
p4c.set_edge_line_width_mapping("weight", [float(edges.weight.min()), float(edges.weight.max())],
                                [0.5, 8], mapping_type="c", style_name=STYLE)
# weak ties fade into the background, strong ties stand out. Colour rather
# than transparency: Cytoscape draws wide translucent edges with a visible
# outline, which looks like doubled edges in the PNG export.
p4c.set_edge_color_mapping("weight", [0.05, 0.5, float(edges.weight.max())],
                           ["#E3E3E3", "#B0B0B0", "#606060"], mapping_type="c", style_name=STYLE)
p4c.set_visual_style(STYLE)

# --- layout ----------------------------------------------------------------
# Edge-weighted Kamada-Kawai keeps strongly tied people close, so the three
# communities separate visibly while weak cross-community ties stay visible.
import itertools, math, requests

comm = {str(r.id): r.community_id for r in nodes.itertuples()}


def positions():
    pos = p4c.get_node_position()
    return {str(i): (float(pos.loc[i, "x"]), float(pos.loc[i, "y"])) for i in pos.index}


def separation(pts):
    """Mean distance within communities over mean distance between them:
    lower means the three groups are more clearly apart."""
    within, between = [], []
    for a, b in itertools.combinations(pts, 2):
        (within if comm[a] == comm[b] else between).append(math.dist(pts[a], pts[b]))
    return (sum(within) / len(within)) / (sum(between) / len(between))


def write_positions(pts):
    names = p4c.get_table_columns("node", ["name"])
    view = p4c.get_network_views()[0]
    # the PUT returns an empty body, which p4c.cyrest_put cannot parse
    r = requests.put(f"http://127.0.0.1:1234/v1/networks/{suid}/views/{view}/nodes", json=[
        {"SUID": int(s), "view": [{"visualProperty": "NODE_X_LOCATION", "value": pts[names.loc[s, "name"]][0]},
                                  {"visualProperty": "NODE_Y_LOCATION", "value": pts[names.loc[s, "name"]][1]}]}
        for s in names.index], timeout=60)
    r.raise_for_status()


# Kamada-Kawai on the topology alone separates the three communities well;
# with edgeAttribute=weight Cytoscape uses the weight as an edge *length*, which
# pulls the strongest ties longest and mixes the groups. The result depends on
# the (random) starting positions, so run it a few times and keep the layout in
# which the three communities are most clearly separated.
best = None
for run in range(6):
    p4c.layout_network("kamada-kawai unweighted=true randomize=true")
    pts = positions(); score = separation(pts)
    xs = [p[0] for p in pts.values()]; ys = [p[1] for p in pts.values()]
    print(f"layout run {run}: separation {score:.3f}, extent {max(xs)-min(xs):.0f} x {max(ys)-min(ys):.0f}")
    if best is None or score < best[0]:
        best = (score, pts)
write_positions(best[1])
print(f"kept layout with separation {best[0]:.3f}")


def remove_overlaps(gap=1.15, rounds=50):
    """Kamada-Kawai ignores node size, so big neighbours can sit on top of each
    other and their edges to a common node look doubled. Nudge overlapping
    pairs apart along their axis until every pair is at least `gap` times the
    sum of their radii apart. Positions are written back through CyREST."""
    dmin, dmax = nodes.degree.min(), nodes.degree.max()
    radius = {str(r.id): (18 + (r.degree - dmin) / (dmax - dmin) * (70 - 18)) / 2
              for r in nodes.itertuples()}
    pos = p4c.get_node_position()
    pts = {str(i): [float(pos.loc[i, "x"]), float(pos.loc[i, "y"])] for i in pos.index}
    for _ in range(rounds):
        moved = 0
        for a, b in itertools.combinations(pts, 2):
            (ax, ay), (bx, by) = pts[a], pts[b]
            d = math.hypot(bx - ax, by - ay)
            need = (radius[a] + radius[b]) * gap
            if d < need:
                if d < 1e-6:
                    ux, uy, d = 1.0, 0.0, 1e-6
                else:
                    ux, uy = (bx - ax) / d, (by - ay) / d
                push = (need - d) / 2
                pts[a][0] -= ux * push; pts[a][1] -= uy * push
                pts[b][0] += ux * push; pts[b][1] += uy * push
                moved += 1
        if not moved:
            break
    write_positions({k: tuple(v) for k, v in pts.items()})
    print(f"overlap removal: done after {_ + 1} rounds")


remove_overlaps()
p4c.fit_content()

# --- exports (tutorial Option 1 and Option 2) -------------------------------
for f in OUT.glob("network*"):
    f.unlink()
p4c.export_image(str(OUT / "network.png"), type="PNG", zoom=300, overwrite_file=True)
# "File > Export > Network and View" = the network view as Cytoscape.js JSON,
# including node positions. The plain "network export" command omits the view,
# so fetch the view through CyREST instead.
view = p4c.get_network_views()[0]
cyjs = p4c.cyrest_get(f"networks/{suid}/views/{view}")
import json
(OUT / "network.cyjs").write_text(json.dumps(cyjs, ensure_ascii=False, indent=1))
p4c.export_visual_styles(str(OUT / "style.json"), type="json", styles=STYLE, overwrite_file=True)
p4c.save_session(str(OUT / "spb_literary_network.cys"), overwrite_file=True)
print("exported:", sorted(p.name for p in OUT.iterdir()))
