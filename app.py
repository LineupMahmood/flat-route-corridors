import os, gzip, math, time as _time, urllib.request, pickle
import osmnx as ox
import networkx as nx
from flask import Flask, request, jsonify

app = Flask(__name__)

GRAPHML_PATH = "sf_walk_network_elevation_v4.graphml"
GRAPHML_GZ_URL = "https://github.com/LineupMahmood/flat-route-api/releases/download/V4/sf_walk_network_elevation_v4.graphml.gz"

if not os.path.exists(GRAPHML_PATH):
    print("Downloading graph...")
    gz_path = GRAPHML_PATH + ".gz"
    urllib.request.urlretrieve(GRAPHML_GZ_URL, gz_path)
    with gzip.open(gz_path, 'rb') as f_in:
        with open(GRAPHML_PATH, 'wb') as f_out:
            f_out.write(f_in.read())
    os.remove(gz_path)

PICKLE_PATH = "sf_corridors_v1.pkl"
print("Loading graph...")
if os.path.exists(PICKLE_PATH):
    with open(PICKLE_PATH, "rb") as f:
        G = pickle.load(f)
    print("Pickle loaded.")
else:
    G = ox.load_graphml(filepath=GRAPHML_PATH)
    with open(PICKLE_PATH, "wb") as f:
        pickle.dump(G, f)
    print("Pickle saved.")

print("Computing edge weights...")
COMFORT_GRADE = 0.02
K = 1500
for u, v, k, data in G.edges(keys=True, data=True):
    grade = float(data.get("grade_abs", 0))
    length = float(data.get("length", 0))
    excess = max(0.0, grade - COMFORT_GRADE)
    data["impedance"] = length * (1 + K * excess ** 2)
print("Ready.")

# ── Corridors ─────────────────────────────────────────────────────────────────
# Each corridor defines a flat section of SF by lat band + lng range.
# Segments are evaluated only within the band relevant to the user's trip.
CORRIDORS = [
    {"name": "Octavia Blvd",    "keyword": "octavia",   "direction": "N-S"},
    {"name": "Valencia Street", "keyword": "valencia",  "direction": "N-S"},
    {"name": "Mission Street",  "keyword": "mission",   "direction": "N-S"},
    {"name": "The Embarcadero", "keyword": "embarcadero","direction": "N-S"},
    {"name": "Market Street",   "keyword": "market",    "direction": "NE-SW"},
    {"name": "Columbus Avenue", "keyword": "columbus",  "direction": "NE-SW"},
    {"name": "Fell Street",     "keyword": "fell",      "direction": "E-W"},
    {"name": "Broadway",        "keyword": "broadway",  "direction": "E-W"},
    {"name": "Brannan Street",  "keyword": "brannan",   "direction": "E-W"},
    {"name": "King Street",     "keyword": "king",      "direction": "E-W"},
    {"name": "Beach Street",    "keyword": "beach",     "direction": "E-W"},
    {"name": "Bay Street",      "keyword": "bay",       "direction": "E-W"},
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def haversine(a, b):
    dlat = (a[0] - b[0]) * 111000
    dlng = (a[1] - b[1]) * 111000 * math.cos(math.radians(a[0]))
    return math.sqrt(dlat**2 + dlng**2)

def path_stats(path):
    total_length = 0
    grades = []
    coords = []
    for i in range(len(path) - 1):
        u, v = path[i], path[i+1]
        ed = G.get_edge_data(u, v)
        if ed:
            edge = min(ed.values(), key=lambda d: float(d.get("grade_abs", 99)))
            total_length += float(edge.get("length", 0))
            grades.append(float(edge.get("grade_abs", 0)))
    for node in path:
        coords.append({"lat": G.nodes[node]["y"], "lng": G.nodes[node]["x"]})
    avg_grade = sum(grades) / len(grades) if grades else 0
    max_grade = max(grades) if grades else 0
    return {
        "coordinates": coords,
        "distanceInMiles": round(total_length / 1609.34, 2),
        "avgGradePct": round(avg_grade * 100, 1),
        "maxGradePct": round(max_grade * 100, 1),
    }

def best_corridor_node(keyword, target_lat, target_lng, lat_band=0.006, lng_band=0.006):
    """
    Find the node on a named corridor closest to (target_lat, target_lng).
    Only considers nodes that sit on edges named with the keyword.
    Returns the flattest such node within the band.
    """
    lat_min = target_lat - lat_band
    lat_max = target_lat + lat_band
    lng_min = target_lng - lng_band
    lng_max = target_lng + lng_band

    candidate_nodes = set()
    for u, v, data in G.edges(data=True):
        name = data.get("name", "")
        if isinstance(name, list):
            name = name[0] if name else ""
        if keyword not in name.lower():
            continue
        for node in [u, v]:
            nx_ = G.nodes[node]["x"]
            ny_ = G.nodes[node]["y"]
            if lat_min < ny_ < lat_max and lng_min < nx_ < lng_max:
                candidate_nodes.add(node)

    if not candidate_nodes:
        return None

    # Among candidates, pick the one with lowest avg adjacent grade
    def avg_grade(n):
        grades = [float(d.get("grade_abs", 0.05))
                  for _, _, d in G.edges(n, data=True)]
        return sum(grades) / len(grades) if grades else 0.05

    return min(candidate_nodes, key=avg_grade)

def corridor_grade_in_band(keyword, lat_min, lat_max):
    """Average grade of corridor edges within a latitude band."""
    grades = []
    for u, v, data in G.edges(data=True):
        name = data.get("name", "")
        if isinstance(name, list):
            name = name[0] if name else ""
        if keyword not in name.lower():
            continue
        mid_lat = (G.nodes[u]["y"] + G.nodes[v]["y"]) / 2
        if lat_min < mid_lat < lat_max:
            grades.append(float(data.get("grade_abs", 0)))
    return sum(grades) / len(grades) if grades else None

def generate_steps(feeder_stats, corridor_stats, exit_stats, corridor_name):
    """Generate 3 plain-English step cards."""
    steps = []

    # Step 1 — walk to corridor
    d1 = feeder_stats["distanceInMiles"]
    if d1 < 0.05:
        steps.append({
            "step": 1,
            "instruction": f"You're already near {corridor_name}. Head onto it.",
            "distanceMiles": d1,
            "gradePct": feeder_stats["avgGradePct"],
            "type": "feeder"
        })
    else:
        steps.append({
            "step": 1,
            "instruction": f"Walk {d1:.2f}mi to reach {corridor_name}.",
            "distanceMiles": d1,
            "gradePct": feeder_stats["avgGradePct"],
            "type": "feeder"
        })

    # Step 2 — walk the corridor
    d2 = corridor_stats["distanceInMiles"]
    g2 = corridor_stats["avgGradePct"]
    feel = "gentle and flat" if g2 < 4 else "mostly gentle" if g2 < 7 else "moderate"
    steps.append({
        "step": 2,
        "instruction": f"Follow {corridor_name} for {d2:.2f}mi — {feel} ({g2}% avg grade).",
        "distanceMiles": d2,
        "gradePct": g2,
        "type": "corridor"
    })

    # Step 3 — walk to destination
    d3 = exit_stats["distanceInMiles"]
    steps.append({
        "step": 3,
        "instruction": f"Leave {corridor_name} and walk {d3:.2f}mi to your destination.",
        "distanceMiles": d3,
        "gradePct": exit_stats["avgGradePct"],
        "type": "exit"
    })

    return steps


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "version": "corridors-v1"}


@app.route("/corridor_route", methods=["GET"])
def corridor_route():
    try:
        start_lat = float(request.args.get("start_lat"))
        start_lng = float(request.args.get("start_lng"))
        end_lat   = float(request.args.get("end_lat"))
        end_lng   = float(request.args.get("end_lng"))

        origin      = ox.distance.nearest_nodes(G, start_lng, start_lat)
        destination = ox.distance.nearest_nodes(G, end_lng, end_lat)

        crow_m = haversine((start_lat, start_lng), (end_lat, end_lng))

        # Direct route grade — baseline to beat
        direct_path = ox.routing.shortest_path(G, origin, destination, weight="length")
        direct_stats = path_stats(direct_path)
        direct_grade = direct_stats["avgGradePct"] / 100

        print(f"Direct route: {direct_stats['distanceInMiles']}mi, {direct_stats['avgGradePct']}% avg")

        # Latitude band for corridor evaluation
        lat_min = min(start_lat, end_lat) - 0.002
        lat_max = max(start_lat, end_lat) + 0.002
        lng_min = min(start_lng, end_lng) - 0.010
        lng_max = max(start_lng, end_lng) + 0.010

        # Score each corridor
        scored = []
        for corridor in CORRIDORS:
            kw = corridor["keyword"]

            # Check corridor is geographically relevant
            cor_grade = corridor_grade_in_band(kw, lat_min, lat_max)
            if cor_grade is None:
                continue  # corridor not present in this band

            improvement = direct_grade - cor_grade
            pct_easier  = (improvement / direct_grade * 100) if direct_grade > 0 else 0

            if pct_easier < 10:
                continue  # not worth suggesting

            # Find entry and exit nodes on the corridor
            entry_node = best_corridor_node(kw, start_lat, start_lng,
                                            lat_band=lat_max-lat_min,
                                            lng_band=lng_max-lng_min)
            exit_node  = best_corridor_node(kw, end_lat, end_lng,
                                            lat_band=lat_max-lat_min,
                                            lng_band=lng_max-lng_min)

            if entry_node is None or exit_node is None or entry_node == exit_node:
                continue

            scored.append({
                "corridor": corridor,
                "cor_grade": cor_grade,
                "pct_easier": pct_easier,
                "entry_node": entry_node,
                "exit_node": exit_node,
            })

        scored.sort(key=lambda x: -x["pct_easier"])

        if not scored:
            # No corridor found — fall back to direct route with a note
            return jsonify({
                "suggestion": "direct",
                "message": "No significantly flatter corridor found for this trip.",
                "directRoute": direct_stats,
                "steps": [{
                    "step": 1,
                    "instruction": f"Walk directly to your destination ({direct_stats['distanceInMiles']}mi, {direct_stats['avgGradePct']}% avg grade).",
                    "distanceMiles": direct_stats["distanceInMiles"],
                    "gradePct": direct_stats["avgGradePct"],
                    "type": "direct"
                }]
            })

        best = scored[0]
        entry_node = best["entry_node"]
        exit_node  = best["exit_node"]
        corridor_name = best["corridor"]["name"]

        print(f"Best corridor: {corridor_name}, {best['pct_easier']:.0f}% easier")

        # Route the 3 segments
        feeder_path   = nx.dijkstra_path(G, origin, entry_node, weight="impedance")
        corridor_path = nx.dijkstra_path(G, entry_node, exit_node, weight="impedance")
        exit_path     = nx.dijkstra_path(G, exit_node, destination, weight="impedance")

        feeder_stats   = path_stats(feeder_path)
        corridor_stats = path_stats(corridor_path)
        exit_stats     = path_stats(exit_path)

        total_miles = (feeder_stats["distanceInMiles"] +
                       corridor_stats["distanceInMiles"] +
                       exit_stats["distanceInMiles"])

        steps = generate_steps(feeder_stats, corridor_stats, exit_stats, corridor_name)

        return jsonify({
            "suggestion": corridor_name,
            "pctEasierThanDirect": round(best["pct_easier"], 0),
            "totalDistanceMiles": round(total_miles, 2),
            "corridorGradePct": round(best["cor_grade"] * 100, 1),
            "directGradePct": direct_stats["avgGradePct"],
            "feederRoute":   feeder_stats,
            "corridorRoute": corridor_stats,
            "exitRoute":     exit_stats,
            "steps": steps,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)