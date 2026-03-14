import os, gzip, math, urllib.request, pickle
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
        u, v = path[i], path[i + 1]
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


def discover_corridors(start_lat, start_lng, end_lat, end_lng):
    """
    Scan every edge in the trip bounding box.
    Group by street name, compute length-weighted average grade,
    and return all named streets with enough span to be useful corridors.
    No hardcoded list — purely data-driven.
    """
    LAT_PAD = 0.006
    LNG_PAD = 0.015
    MIN_SPAN_M = 350     # corridor must be at least 350m long in this band
    MIN_EDGES  = 4       # need at least 4 edges to be a real street segment

    lat_min = min(start_lat, end_lat) - LAT_PAD
    lat_max = max(start_lat, end_lat) + LAT_PAD
    lng_min = min(start_lng, end_lng) - LNG_PAD
    lng_max = max(start_lng, end_lng) + LNG_PAD

    streets = {}  # name_key -> dict

    for u, v, data in G.edges(data=True):
        nu, nv = G.nodes[u], G.nodes[v]
        mid_lat = (nu["y"] + nv["y"]) / 2
        mid_lng = (nu["x"] + nv["x"]) / 2

        if not (lat_min < mid_lat < lat_max and lng_min < mid_lng < lng_max):
            continue

        name = data.get("name", "")
        if isinstance(name, list):
            name = name[0] if name else ""
        name = name.strip()
        if not name or len(name) < 4:
            continue

        # Only include edges that are walkable by OSM highway classification
        highway = data.get("highway", "")
        if isinstance(highway, list):
            highway = highway[0] if highway else ""
        walkable = {
            "residential", "living_street", "pedestrian", "footway",
            "path", "track", "unclassified", "tertiary", "tertiary_link",
            "secondary", "secondary_link", "primary", "primary_link",
            "service", "steps", "corridor"
        }
        if highway not in walkable:
            continue

        name_key = name.lower()
        grade  = float(data.get("grade_abs", 0))
        length = float(data.get("length", 0))

        if name_key not in streets:
            streets[name_key] = {
                "name": name,
                "grades": [],
                "lengths": [],
                "nodes": set(),
                "lats": [],
                "lngs": [],
            }

        s = streets[name_key]
        s["grades"].append(grade)
        s["lengths"].append(length)
        s["nodes"].update([u, v])
        s["lats"].extend([nu["y"], nv["y"]])
        s["lngs"].extend([nu["x"], nv["x"]])

    candidates = []
    for name_key, s in streets.items():
        if len(s["grades"]) < MIN_EDGES:
            continue

        total_length = sum(s["lengths"])
        if total_length < MIN_SPAN_M:
            continue

        # Length-weighted average grade — the core scoring metric
        avg_grade = sum(g * l for g, l in zip(s["grades"], s["lengths"])) / total_length

        # Geographic span of this street within the band
        lats, lngs = s["lats"], s["lngs"]
        avg_lat = sum(lats) / len(lats)
        lat_span_m = (max(lats) - min(lats)) * 111000
        lng_span_m = (max(lngs) - min(lngs)) * 111000 * math.cos(math.radians(avg_lat))
        span_m = math.sqrt(lat_span_m**2 + lng_span_m**2)

        if span_m < MIN_SPAN_M:
            continue

        candidates.append({
            "name": s["name"],
            "avg_grade": avg_grade,
            "total_length_m": total_length,
            "span_m": span_m,
            "nodes": s["nodes"],
        })

    print(f"  Discovered {len(candidates)} candidate corridors in bounding box")
    return candidates


def best_node_near(nodes, target_lat, target_lng):
    """Return the node in `nodes` closest to the target coordinate."""
    return min(
        nodes,
        key=lambda n: haversine(
            (G.nodes[n]["y"], G.nodes[n]["x"]),
            (target_lat, target_lng)
        )
    )


def generate_steps(feeder_stats, corridor_stats, exit_stats, corridor_name):
    steps = []
    d1 = feeder_stats["distanceInMiles"]
    if d1 < 0.05:
        steps.append({
            "step": 1,
            "instruction": f"You're already near {corridor_name}. Head onto it.",
            "distanceMiles": d1, "gradePct": feeder_stats["avgGradePct"], "type": "feeder"
        })
    else:
        steps.append({
            "step": 1,
            "instruction": f"Walk {d1:.2f}mi to reach {corridor_name}.",
            "distanceMiles": d1, "gradePct": feeder_stats["avgGradePct"], "type": "feeder"
        })
    d2 = corridor_stats["distanceInMiles"]
    g2 = corridor_stats["avgGradePct"]
    feel = "gentle and flat" if g2 < 4 else "mostly gentle" if g2 < 7 else "moderate"
    steps.append({
        "step": 2,
        "instruction": f"Follow {corridor_name} for {d2:.2f}mi — {feel} ({g2}% avg grade).",
        "distanceMiles": d2, "gradePct": g2, "type": "corridor"
    })
    d3 = exit_stats["distanceInMiles"]
    steps.append({
        "step": 3,
        "instruction": f"Leave {corridor_name} and walk {d3:.2f}mi to your destination.",
        "distanceMiles": d3, "gradePct": exit_stats["avgGradePct"], "type": "exit"
    })
    return steps


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "version": "corridors-v2-dynamic"}


@app.route("/corridor_route", methods=["GET"])
def corridor_route():
    try:
        start_lat = float(request.args.get("start_lat"))
        start_lng = float(request.args.get("start_lng"))
        end_lat   = float(request.args.get("end_lat"))
        end_lng   = float(request.args.get("end_lng"))

        origin      = ox.distance.nearest_nodes(G, start_lng, start_lat)
        destination = ox.distance.nearest_nodes(G, end_lng,   end_lat)
        crow_m      = haversine((start_lat, start_lng), (end_lat, end_lng))

        # ── Baseline: direct route ─────────────────────────────────────────
        direct_path  = ox.routing.shortest_path(G, origin, destination, weight="length")
        direct_stats = path_stats(direct_path)
        direct_grade = direct_stats["avgGradePct"] / 100

        print(f"Direct: {direct_stats['distanceInMiles']}mi, {direct_stats['avgGradePct']}% avg")

        if direct_grade < 0.04:
            return jsonify({
                "suggestion": "direct",
                "message": "Your direct route is already gentle — no detour needed.",
                "directRoute": direct_stats,
                "totalDistanceMiles": direct_stats["distanceInMiles"],
                "steps": [{
                    "step": 1,
                    "instruction": f"Walk directly to your destination — already a gentle route ({direct_stats['avgGradePct']}% avg grade).",
                    "distanceMiles": direct_stats["distanceInMiles"],
                    "gradePct": direct_stats["avgGradePct"],
                    "type": "direct"
                }]
            })

        # ── Discover every named street in the bounding box ────────────────
        candidates = discover_corridors(start_lat, start_lng, end_lat, end_lng)

        scored = []
        for c in candidates:
            # How much flatter is this street vs the direct route?
            improvement  = direct_grade - c["avg_grade"]
            pct_easier   = (improvement / direct_grade * 100) if direct_grade > 0 else 0

            if pct_easier < 10:
                continue  # not meaningfully flatter

            # Find the closest entry/exit nodes on this street
            entry_node = best_node_near(c["nodes"], start_lat, start_lng)
            exit_node  = best_node_near(c["nodes"], end_lat,   end_lng)

            if entry_node is None or exit_node is None or entry_node == exit_node:
                continue

            # Corridor must have enough span between entry and exit
            entry_coords = (G.nodes[entry_node]["y"], G.nodes[entry_node]["x"])
            exit_coords  = (G.nodes[exit_node]["y"],  G.nodes[exit_node]["x"])
            corridor_span_m = haversine(entry_coords, exit_coords)
            if corridor_span_m < 300:
                print(f"  Skip {c['name']} — corridor span too short ({corridor_span_m:.0f}m)")
                continue

            # Reject if the detour is wildly out of the way
            feeder_dist = haversine((start_lat, start_lng), entry_coords)
            exit_dist   = haversine((end_lat,   end_lng),   exit_coords)
            # Reject if feeder alone is longer than half the total trip
            if feeder_dist > crow_m * 0.5:
                print(f"  Skip {c['name']} — feeder too long ({feeder_dist:.0f}m vs {crow_m:.0f}m trip)")
                continue

            # Reject if exit alone is longer than half the total trip
            if exit_dist > crow_m * 0.5:
                print(f"  Skip {c['name']} — exit too long ({exit_dist:.0f}m vs {crow_m:.0f}m trip)")
                continue

            detour_ratio = (feeder_dist + exit_dist) / crow_m
            if detour_ratio > 1.4:
                print(f"  Skip {c['name']} — too much detour ({detour_ratio:.1f}x crow-flies)")
                continue

            # Score = grade improvement divided by detour cost
            # A corridor 0.2x out of the way beats one that's 1.3x out of the way
            # even if the far one is slightly flatter
            span_bonus = min(c["span_m"] / 1000, 1.0)  # caps at 1.0 for 1km+
            score = pct_easier * (1 + 0.1 * span_bonus) / (1 + detour_ratio)

            scored.append({
                "name": c["name"],
                "avg_grade": c["avg_grade"],
                "pct_easier": pct_easier,
                "score": score,
                "entry_node": entry_node,
                "exit_node": exit_node,
            })
            print(f"  {c['name']}: {pct_easier:.1f}% easier, score={score:.1f}")

        scored.sort(key=lambda x: -x["score"])

        if not scored:
            return jsonify({
                "suggestion": "direct",
                "message": "No significantly flatter street found for this trip.",
                "directRoute": direct_stats,
                "totalDistanceMiles": direct_stats["distanceInMiles"],
                "steps": [{
                    "step": 1,
                    "instruction": f"Walk directly to your destination ({direct_stats['distanceInMiles']}mi, {direct_stats['avgGradePct']}% avg grade).",
                    "distanceMiles": direct_stats["distanceInMiles"],
                    "gradePct": direct_stats["avgGradePct"],
                    "type": "direct"
                }]
            })

        best = scored[0]
        corridor_name = best["name"]
        entry_node    = best["entry_node"]
        exit_node     = best["exit_node"]

        print(f"Winner: {corridor_name} — {best['pct_easier']:.0f}% easier than direct")

        # ── Route the 3 segments ───────────────────────────────────────────
        feeder_path   = nx.dijkstra_path(G, origin,      entry_node,  weight="impedance")
        corridor_path = nx.dijkstra_path(G, entry_node,  exit_node,   weight="impedance")
        exit_path     = nx.dijkstra_path(G, exit_node,   destination, weight="impedance")

        feeder_stats   = path_stats(feeder_path)
        corridor_stats = path_stats(corridor_path)
        exit_stats     = path_stats(exit_path)

        total_miles = (feeder_stats["distanceInMiles"] +
                       corridor_stats["distanceInMiles"] +
                       exit_stats["distanceInMiles"])

        # Final sanity check: corridor route must not be >1.8x the direct distance
        if total_miles > direct_stats["distanceInMiles"] * 1.8:
            print(f"⚠️ {corridor_name} total {total_miles:.2f}mi > 1.8x direct {direct_stats['distanceInMiles']:.2f}mi — falling back to direct")
            return jsonify({
                "suggestion": "direct",
                "message": "No nearby corridor found that doesn't add too much distance.",
                "directRoute": direct_stats,
                "totalDistanceMiles": direct_stats["distanceInMiles"],
                "steps": [{
                    "step": 1,
                    "instruction": f"Walk directly to your destination ({direct_stats['distanceInMiles']}mi, {direct_stats['avgGradePct']}% avg grade).",
                    "distanceMiles": direct_stats["distanceInMiles"],
                    "gradePct": direct_stats["avgGradePct"],
                    "type": "direct"
                }]
            })

        steps = generate_steps(feeder_stats, corridor_stats, exit_stats, corridor_name)

        return jsonify({
            "suggestion": corridor_name,
            "pctEasierThanDirect": round(best["pct_easier"], 0),
            "totalDistanceMiles": round(total_miles, 2),
            "corridorGradePct": round(best["avg_grade"] * 100, 1),
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