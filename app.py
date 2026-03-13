import os
import gzip
import math
import time as _time

def has_backtrack(path, max_reversals=3):
    """
    Rejects routes that repeatedly oscillate toward/away from destination.
    Octavia-style overshoots are fine. NE→SE→NE→SE zigzags are not.
    """
    coords = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in path]
    dest = coords[-1]
    def dist_to_dest(c):
        return math.sqrt(((c[0]-dest[0])*111000)**2 + ((c[1]-dest[1])*111000)**2)

    dists = [dist_to_dest(c) for c in coords]
    crow = dists[0]
    if crow < 50:
        return False

    reversals = 0
    min_seen = dists[0]
    for i in range(1, len(dists)):
        if dists[i] < min_seen:
            min_seen = dists[i]
        elif dists[i] > min_seen + crow * 0.15:
            reversals += 1
            min_seen = dists[i]

    return reversals > max_reversals

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
COMFORT_GRADE = 0.02
K_GENTLE   = 1500
K_MODERATE = 600
for u, v, k, data in G.edges(keys=True, data=True):
    grade = float(data.get("grade_abs", 0))
    length = float(data.get("length", 0))
    excess = max(0.0, grade - COMFORT_GRADE)
    highway = str(data.get("highway", ""))
    # Penalize unpleasant walking streets (major roads, highways)
    if isinstance(highway, list):
        highway = highway[0] if highway else ""
    # Geographic exclusion: penalize Van Ness corridor heavily
    road_penalty = 1.0
    data["impedance_gentle"]   = length * road_penalty * (1 + K_GENTLE   * excess ** 2)
    data["impedance_moderate"] = length * road_penalty * (1 + K_MODERATE * excess ** 2)
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
        "_difficulty": avg_grade * 0.7 + max_grade * 0.3 + (total_length / 1609.34) * 0.01
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
@app.route("/debug_grade", methods=["GET"])
def debug_grade():
    results = []
    for u, v, data in G.edges(data=True):
        u_data = G.nodes[u]
        v_data = G.nodes[v]
        # Check if edge is in Octavia or Van Ness corridor
        mid_lng = (u_data["x"] + v_data["x"]) / 2
        mid_lat = (u_data["y"] + v_data["y"]) / 2
        if 37.794 < mid_lat < 37.800:
            if -122.4255 < mid_lng < -122.4240:  # Octavia
                results.append({"street": "Octavia", "grade_abs": data.get("grade_abs"), "length": data.get("length"), "highway": str(data.get("highway", "MISSING"))})
            elif -122.4240 < mid_lng < -122.4228:  # Van Ness
                results.append({"street": "VanNess", "grade_abs": data.get("grade_abs"), "length": data.get("length"), "highway": str(data.get("highway", "MISSING"))})
    return jsonify(results)
    
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

        # Corridor-based routing: sample N/S streets between origin and destination
        # Route origin → corridor_waypoint → destination for each corridor
        print("Running corridor-based routing...")
        _t0 = _time.time()
        orig_lng = G.nodes[origin]["x"]
        dest_lng = G.nodes[destination]["x"]
        orig_lat = G.nodes[origin]["y"]
        dest_lat = G.nodes[destination]["y"]
        mid_lat = orig_lat  # waypoint at origin latitude = corridor entry point

        # Sample corridors across the full longitude range plus small buffer
        lng_min = min(orig_lng, dest_lng) - 0.006
        lng_max = max(orig_lng, dest_lng) + 0.006
        step = 0.0008
        n_steps = int((lng_max - lng_min) / step) + 1
        corridor_lngs = [lng_min + i * step for i in range(n_steps)]

        seen_waypoints = set()
        for corridor_lng in corridor_lngs:
            try:
                wp_north = ox.distance.nearest_nodes(G, corridor_lng, orig_lat)
                wp_south = ox.distance.nearest_nodes(G, corridor_lng, dest_lat)
                key = (wp_north, wp_south)
                if key in seen_waypoints or wp_north == origin or wp_south == destination:
                    continue
                seen_waypoints.add(key)
                path1 = ox.routing.shortest_path(G, origin, wp_north, weight="impedance_gentle")
                path2 = ox.routing.shortest_path(G, wp_north, wp_south, weight="impedance_gentle")
                path3 = ox.routing.shortest_path(G, wp_south, destination, weight="impedance_gentle")
                if path1 and path2 and path3:
                    full_path = path1 + path2[1:] + path3[1:]
                    all_routes.append(analyze_route(full_path))
            except Exception as e:
                continue
        print(f"[corridor] corridors={len(seen_waypoints)} elapsed={_time.time()-_t0:.1f}s")

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
