import os
import gzip
import math
import urllib.request
import osmnx as ox
import networkx as nx
from flask import Flask, request, jsonify
from shapely.geometry import LineString

app = Flask(__name__)

GRAPHML_PATH = "sf_walk_network_elevation_v3.graphml"
GRAPHML_GZ_URL = "https://github.com/LineupMahmood/flat-route-api/releases/download/V.3/sf_walk_network_elevation_v3.graphml.gz"

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
PICKLE_PATH = "sf_walk_network_v5.pkl"

print("Loading elevation network...")
if os.path.exists(PICKLE_PATH):
    print("Found pickle cache, loading fast...")
    with open(PICKLE_PATH, "rb") as f:
        G = pickle.load(f)
    print("Pickle loaded.")
else:
    print("No pickle found, loading from graphml (slow, one-time)...")
    G = ox.load_graphml(filepath=GRAPHML_PATH)
    for u, v, k, data in G.edges(keys=True, data=True):
        grade = float(data.get("grade_abs", 0))
        length = float(data.get("length", 0))

        # CHANGE: smooth quadratic curve, no hard cutoff.
        # 5% grade  → 1.075x multiplier (barely penalized)
        # 10% grade → 1.30x multiplier  (was 999999x before)
        # 20% grade → 2.20x multiplier  (steep but not impassable)
        # This stops the router forcing absurd detours to avoid moderate hills.
        data["impedance_high"] = length * (1 + 30 * grade ** 2)

        # Stricter variant — used for finding the flattest option.
        # 10% grade → 1.80x, 20% grade → 4.20x
        data["impedance_max"] = length * (1 + 80 * grade ** 2)

    print("Saving pickle cache for fast future loads...")
    with open(PICKLE_PATH, "wb") as f:
        pickle.dump(G, f)

print("Network ready. Server starting...")


# ── Utilities ─────────────────────────────────────────────────────────────────

def haversine_dist(a, b):
    """Distance in meters between two (lat, lng) tuples."""
    dlat = (a[0] - b[0]) * 111000
    dlng = (a[1] - b[1]) * 111000 * math.cos(math.radians(a[0]))
    return math.sqrt(dlat ** 2 + dlng ** 2)


def straight_line_dist_miles(lat1, lng1, lat2, lng2):
    return haversine_dist((lat1, lng1), (lat2, lng2)) / 1609.34


def remove_reversals(coords, threshold_m=20):
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
    Build polyline from edge geometries ONLY — never insert node coordinates.
    After consolidate_intersections, node centroids don't sit on edge geometry
    endpoints, so inserting them creates ping-pong artifacts.
    """
    coords = []

    for i in range(len(route) - 1):
        u, v = route[i], route[i + 1]
        edge_data = G.get_edge_data(u, v)
        edge = min(edge_data.values(), key=lambda d: d.get("length", 0)) if edge_data else {}
        geom = edge.get("geometry")

        if geom is not None:
            pts = list(geom.coords)
        else:
            pts = [
                (G.nodes[u]["x"], G.nodes[u]["y"]),
                (G.nodes[v]["x"], G.nodes[v]["y"])
            ]

        u_pos = (G.nodes[u]["y"], G.nodes[u]["x"])
        if haversine_dist(u_pos, (pts[0][1], pts[0][0])) > haversine_dist(u_pos, (pts[-1][1], pts[-1][0])):
            pts = pts[::-1]

        for lng, lat in pts[:-1]:
            coords.append({"lat": lat, "lng": lng})

    if len(route) >= 2:
        u, v = route[-2], route[-1]
        edge_data = G.get_edge_data(u, v)
        edge = min(edge_data.values(), key=lambda d: d.get("length", 0)) if edge_data else {}
        geom = edge.get("geometry")
        if geom is not None:
            pts = list(geom.coords)
            u_pos = (G.nodes[u]["y"], G.nodes[u]["x"])
            if haversine_dist(u_pos, (pts[0][1], pts[0][0])) > haversine_dist(u_pos, (pts[-1][1], pts[-1][0])):
                pts = pts[::-1]
            lng, lat = pts[-1]
            coords.append({"lat": lat, "lng": lng})
        else:
            coords.append({"lat": G.nodes[v]["y"], "lng": G.nodes[v]["x"]})

    return remove_reversals(coords)


# ── Route analysis ────────────────────────────────────────────────────────────

def analyze_route(route):
    total_gain = 0
    total_length = 0
    grades = []

    for i in range(len(route) - 1):
        u, v = route[i], route[i + 1]
        edge_data = G.get_edge_data(u, v)
        edge = edge_data[0] if edge_data else {}
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
            "impedance_high": data.get("impedance_high")
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

        for weight in ["impedance_high", "impedance_max", "length"]:
            r = ox.routing.shortest_path(G, origin, destination, weight=weight)
            if r:
                all_routes.append(analyze_route(r))

        origin_lat = G.nodes[origin]["y"]
        origin_lng = G.nodes[origin]["x"]
        dest_lat = G.nodes[destination]["y"]
        dest_lng = G.nodes[destination]["x"]

        for weight in ["impedance_high", "impedance_max"]:
            for fractions in [[0.33, 0.66], [0.25, 0.75], [0.4, 0.6]]:
                try:
                    waypoints = []
                    for f in fractions:
                        wlat = origin_lat + (dest_lat - origin_lat) * f
                        wlng = origin_lng + (dest_lng - origin_lng) * f
                        wnode = ox.distance.nearest_nodes(G, wlng, wlat)
                        if wnode not in (origin, destination):
                            waypoints.append(wnode)

                    if len(waypoints) < 2:
                        continue

                    full_route = []
                    nodes_seq = [origin] + waypoints + [destination]
                    valid = True
                    for i in range(len(nodes_seq) - 1):
                        seg = ox.routing.shortest_path(G, nodes_seq[i], nodes_seq[i + 1], weight=weight)
                        if not seg:
                            valid = False
                            break
                        if full_route:
                            full_route += seg[1:]
                        else:
                            full_route = seg

                    if valid and full_route:
                        all_routes.append(analyze_route(full_route))
                except:
                    pass

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
        max_allowed_miles = max(crow_flies_miles * 4.0, 0.5)
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

