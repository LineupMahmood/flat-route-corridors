import os
import gzip
import math
import urllib.request
import osmnx as ox
import networkx as nx
from flask import Flask, request, jsonify
from shapely.geometry import LineString

app = Flask(__name__)

GRAPHML_PATH = "sf_walk_network_elevation_v4.graphml"
GRAPHML_GZ_URL = "https://github.com/LineupMahmood/flat-route-api/releases/download/V4/sf_walk_network_elevation_v4.graphml.gz"

if not os.path.exists(GRAPHML_PATH):
    print("Graph file not found. Downloading...")
    gz_path = GRAPHML_PATH + ".gz"
    urllib.request.urlretrieve(GRAPHML_GZ_URL, gz_path)
    print("Download complete. Decompressing...")
    with gzip.open(gz_path, 'rb') as f_in:
        with open(GRAPHML_PATH, 'wb') as f_out:
            f_out.write(f_in.read())
    os.remove(gz_path)
    print("Decompression complete.")

import pickle

# v5 — new smooth impedance weights (no hard cutoff)
# Changing this forces Railway to rebuild the pickle with new weights
PICKLE_PATH = "sf_walk_network_v9.pkl"

print("Loading elevation network...")
if os.path.exists(PICKLE_PATH):
    print("Found pickle cache, loading fast...")
    with open(PICKLE_PATH, "rb") as f:
        G = pickle.load(f)
    print("Pickle loaded.")
else:
    print("No pickle found, loading from graphml (slow, one-time)...")
    G = ox.load_graphml(filepath=GRAPHML_PATH)
    print("Saving pickle cache for fast future loads...")
    with open(PICKLE_PATH, "wb") as f:
        pickle.dump(G, f)

# Always recompute weights — never trust what's in the pickle
print("Computing edge weights...")
COMFORT_GRADE = 0.05
K_GENTLE   = 1000
K_MODERATE = 400
for u, v, k, data in G.edges(keys=True, data=True):
    grade = float(data.get("grade_abs", 0))
    length = float(data.get("length", 0))
    excess = max(0.0, grade - COMFORT_GRADE)
    data["impedance_gentle"]   = length * (1 + K_GENTLE   * excess ** 2)
    data["impedance_moderate"] = length * (1 + K_MODERATE * excess ** 2)
print("Weights ready.")

print("Network ready. Server starting...")


# ── Utilities ─────────────────────────────────────────────────────────────────

def haversine_dist(a, b):
    """Distance in meters between two (lat, lng) tuples."""
    dlat = (a[0] - b[0]) * 111000
    dlng = (a[1] - b[1]) * 111000 * math.cos(math.radians(a[0]))
    return math.sqrt(dlat ** 2 + dlng ** 2)


def straight_line_dist_miles(lat1, lng1, lat2, lng2):
    return haversine_dist((lat1, lng1), (lat2, lng2)) / 1609.34


def remove_reversals(coords, threshold_m=50):
    """
    Remove A→B→A ping-pong artifacts at edge junctions.
    Also deduplicates exact consecutive duplicates.
    """
    def dist(a, b):
        dlat = (a["lat"] - b["lat"]) * 111000
        dlng = (a["lng"] - b["lng"]) * 111000 * math.cos(math.radians(a["lat"]))
        return math.sqrt(dlat ** 2 + dlng ** 2)

    changed = True
    while changed:
        changed = False
        result = [coords[0]]
        i = 1
        while i < len(coords) - 1:
            prev = result[-1]
            curr = coords[i]
            nxt = coords[i + 1]
            if (dist(prev, curr) < threshold_m
                    and dist(curr, nxt) < threshold_m
                    and dist(prev, nxt) < dist(prev, curr)):
                changed = True
                i += 1
            else:
                result.append(curr)
                i += 1
        result.append(coords[-1])
        coords = result

    deduped = [coords[0]]
    for pt in coords[1:]:
        if pt["lat"] != deduped[-1]["lat"] or pt["lng"] != deduped[-1]["lng"]:
            deduped.append(pt)
    return deduped


# ── Route geometry ────────────────────────────────────────────────────────────

def extract_route_coords(route):
    """
    Node-coordinate-only polyline. Yen's guarantees no repeated nodes,
    so this produces a clean sequence with no orientation or loop artifacts.
    """
    coords = []
    for node in route:
        coords.append({
            "lat": G.nodes[node]["y"],
            "lng": G.nodes[node]["x"]
        })
    return coords

# ── Route analysis ────────────────────────────────────────────────────────────

def analyze_route(route):
    total_gain = 0
    total_length = 0
    grades = []

    for i in range(len(route) - 1):
        u, v = route[i], route[i + 1]
        edge_data = G.get_edge_data(u, v)
        # Pick the flattest edge between these two nodes, matching Yen's selection
        edge = min(edge_data.values(), key=lambda d: float(d.get("grade_abs") or 0)) if edge_data else {}
        length = float(edge.get("length") or 0)
        grade = float(edge.get("grade") or 0)
        grade_abs = abs(float(edge.get("grade_abs") or abs(grade)))
        if length * grade > 0:
            total_gain += length * grade
        total_length += length
        if length > 0:
            grades.append(grade_abs)

    coords = extract_route_coords(route)
    max_grade = max(grades) if grades else 0
    avg_grade = sum(grades) / len(grades) if grades else 0

    return {
        "coordinates": coords,
        "distanceInMiles": round(total_length / 1609.34, 2),
        "elevationGainFt": round(total_gain * 3.281, 1),
        "maxGradePct": round(max_grade * 100, 1),
        "avgGradePct": round(avg_grade * 100, 1),
        "_difficulty": avg_grade * 0.7 + max_grade * 0.3
    }


def deduplicate_routes(routes):
    unique = []
    for r in routes:
        coords = r["coordinates"]
        if len(coords) < 2:
            continue
        is_dup = False
        for u in unique:
            u_coords = u["coordinates"]
            mid = len(coords) // 2
            u_mid = len(u_coords) // 2
            same_dist = abs(r["distanceInMiles"] - u["distanceInMiles"]) < 0.1
            same_grade = abs(r["avgGradePct"] - u["avgGradePct"]) < 0.3
            if same_dist and same_grade and mid < len(coords) and u_mid < len(u_coords):
                dlat = coords[mid]["lat"] - u_coords[u_mid]["lat"]
                dlng = coords[mid]["lng"] - u_coords[u_mid]["lng"]
                if math.sqrt(dlat ** 2 + dlng ** 2) * 111000 < 100:
                    is_dup = True
                    break
            if mid < len(coords) and u_mid < len(u_coords):
                dlat = coords[mid]["lat"] - u_coords[u_mid]["lat"]
                dlng = coords[mid]["lng"] - u_coords[u_mid]["lng"]
                if math.sqrt(dlat ** 2 + dlng ** 2) * 111000 < 40:
                    is_dup = True
                    break
        if not is_dup:
            unique.append(r)
    return unique


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    sample = []
    for u, v, data in list(G.edges(data=True))[:5]:
        sample.append({
            "grade_abs": data.get("grade_abs"),
            "impedance_gentle": data.get("impedance_gentle"),
            "impedance_moderate": data.get("impedance_moderate")
        })
    return {"status": "ok", "version": "v9-smooth-impedance", "sample_edges": sample}


@app.route("/route", methods=["GET"])
def get_route():
    try:
        if request.args.get("start") and request.args.get("end"):
            start_lat, start_lng = map(float, request.args.get("start").split(","))
            end_lat, end_lng = map(float, request.args.get("end").split(","))
        else:
            start_lat = float(request.args.get("start_lat"))
            start_lng = float(request.args.get("start_lng"))
            end_lat = float(request.args.get("end_lat"))
            end_lng = float(request.args.get("end_lng"))

        origin = ox.distance.nearest_nodes(G, start_lng, start_lat)
        destination = ox.distance.nearest_nodes(G, end_lng, end_lat)

        # Straight-line distance — used for the 2x distance cap below
        crow_flies_miles = straight_line_dist_miles(start_lat, start_lng, end_lat, end_lng)

        all_routes = []

        for weight in ["impedance_gentle", "impedance_moderate", "length"]:
            r = ox.routing.shortest_path(G, origin, destination, weight=weight)
            if r:
                all_routes.append(analyze_route(r))

        # Yen's k-shortest paths — finds genuinely different routes, no hardcoded waypoints
        print("Building simple graph for Yen's algorithm...")
        G_simple = nx.DiGraph()
        for u, v, data in G.edges(data=True):
            imp = data.get("impedance_gentle", float("inf"))
            if not G_simple.has_edge(u, v) or imp < G_simple[u][v]["impedance_gentle"]:
                G_simple.add_edge(u, v, **data)

        try:
            candidate_count = 0
            for path in nx.shortest_simple_paths(G_simple, origin, destination, weight="impedance_gentle"):
                candidate_count += 1
                if candidate_count > 50:
                    break
                all_routes.append(analyze_route(path))
        except Exception as e:
            print(f"Yen's algorithm error: {e}")
        print(f"📊 Before dedup: {len(all_routes)} routes")
        for r in all_routes:
            print(f"   {r['distanceInMiles']}mi avg={r['avgGradePct']}% max={r['maxGradePct']}%")

        unique_routes = deduplicate_routes(all_routes)
        print(f"📊 After dedup: {len(unique_routes)} routes")
        unique_routes.sort(key=lambda r: r["_difficulty"])

        if not unique_routes:
            return jsonify({"error": "No routes found"}), 500

        # CHANGE: 2x straight-line distance cap.
        # Prevents the router picking an absurd detour just to avoid a moderate hill.
        # Floor of 0.5mi so very short trips still get reasonable options.
        max_allowed_miles = max(crow_flies_miles * 6.0, 1.5)
        filtered = [r for r in unique_routes
                    if r["distanceInMiles"] <= max_allowed_miles
                    and r["maxGradePct"] <= 20.0]

        if not filtered:
            print("⚠️ Distance cap filtered all routes, falling back to uncapped")
            filtered = unique_routes

        for r in filtered:
            r.pop("_difficulty", None)

        flat = filtered[0]
        short = min(filtered, key=lambda r: r["distanceInMiles"])

        print(f"✅ crow_flies={crow_flies_miles:.2f}mi cap={max_allowed_miles:.2f}mi")
        print(f"✅ Returning {len(filtered)} routes, easiest: avg={filtered[0]['avgGradePct']}%, max={filtered[0]['maxGradePct']}%")

        return jsonify({
            "flatRoute": flat,
            "shortRoute": short,
            "allRoutes": filtered[:6]
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)

