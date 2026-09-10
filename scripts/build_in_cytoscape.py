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
p4c.layout_network("kamada-kawai edgeAttribute=weight unweighted=false")
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
