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

PICKLE_PATH = "sf_walk_v10.pkl"
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
K = 2000

ARTERIAL_HIGHWAY = {"primary", "trunk", "motorway"}
arterial_nodes = set()
for u, v, data in G.edges(data=True):
    hw = data.get("highway", "")
    if isinstance(hw, list):
        hw = hw[0] if hw else ""
    lanes_raw = data.get("lanes", "0")
    try:
        lanes = int(str(lanes_raw).split(";")[0].strip())
    except:
        lanes = 0
    if hw in ARTERIAL_HIGHWAY or lanes >= 3:
        arterial_nodes.add(u)
        arterial_nodes.add(v)

print(f"Arterial nodes: {len(arterial_nodes)}")

for u, v, k, data in G.edges(keys=True, data=True):
    grade = float(data.get("grade_abs", 0))
    length = float(data.get("length", 0))
    excess = max(0.0, grade - COMFORT_GRADE)
    hw = data.get("highway", "")
    if isinstance(hw, list):
        hw = hw[0] if hw else ""
    lanes_raw = data.get("lanes", "0")
    try:
        edge_lanes = int(str(lanes_raw).split(";")[0].strip())
    except:
        edge_lanes = 0
    is_arterial_edge = hw in ARTERIAL_HIGHWAY or edge_lanes >= 3
    both_arterial = (u in arterial_nodes and v in arterial_nodes)
    arterial_penalty = 2.5 if (is_arterial_edge or both_arterial) else 1.0
    data["impedance"] = length * arterial_penalty * (1 + K * excess ** 2)

print("Ready.")


def haversine(a, b):
    dlat = (a[0] - b[0]) * 111000
    dlng = (a[1] - b[1]) * 111000 * math.cos(math.radians(a[0]))
    return math.sqrt(dlat**2 + dlng**2)


def analyze_route(path):
    total_length = 0
    total_gain = 0
    grades = []
    coords = []
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        ed = G.get_edge_data(u, v)
        if ed:
            edge = min(ed.values(), key=lambda d: float(d.get("grade_abs", 99)))
            length = float(edge.get("length", 0))
            grade_abs = float(edge.get("grade_abs", 0))
            grade = float(edge.get("grade", 0))
            total_length += length
            if length * grade > 0:
                total_gain += length * grade
            if length > 0:
                grades.append(grade_abs)
    for node in path:
        coords.append({"lat": G.nodes[node]["y"], "lng": G.nodes[node]["x"]})
    avg_grade = sum(grades) / len(grades) if grades else 0
    max_grade = max(grades) if grades else 0
    return {
        "coordinates": coords,
        "distanceInMiles": round(total_length / 1609.34, 2),
        "elevationGainFt": round(total_gain * 3.281, 1),
        "avgGradePct": round(avg_grade * 100, 1),
        "maxGradePct": round(max_grade * 100, 1),
        "_difficulty": avg_grade * 0.7 + max_grade * 0.3 + (total_length / 1609.34) * 0.01
    }


@app.route("/health")
def health():
    return {"status": "ok", "version": "v10-clean-dijkstra"}


@app.route("/route")
def get_route():
    try:
        start_lat = float(request.args.get("start_lat"))
        start_lng = float(request.args.get("start_lng"))
        end_lat   = float(request.args.get("end_lat"))
        end_lng   = float(request.args.get("end_lng"))

        origin      = ox.distance.nearest_nodes(G, start_lng, start_lat)
        destination = ox.distance.nearest_nodes(G, end_lng,   end_lat)
        crow_miles  = haversine((start_lat, start_lng), (end_lat, end_lng)) / 1609.34

        print(f"Trip: ({start_lat},{start_lng}) → ({end_lat},{end_lng}), crow={crow_miles:.2f}mi")

        routes = []
        for weight in ["impedance", "length"]:
            path = ox.routing.shortest_path(G, origin, destination, weight=weight)
            if path:
                stats = analyze_route(path)
                print(f"  [{weight}] {stats['distanceInMiles']}mi avg={stats['avgGradePct']}% max={stats['maxGradePct']}%")
                routes.append(stats)

        if not routes:
            return jsonify({"error": "No routes found"}), 500

        routes.sort(key=lambda r: r["_difficulty"])
        max_miles = max(crow_miles * 3.0, 1.5)
        filtered = [r for r in routes if r["distanceInMiles"] <= max_miles]
        if not filtered:
            filtered = routes

        for r in filtered:
            r.pop("_difficulty", None)

        flat  = filtered[0]
        short = min(filtered, key=lambda r: r["distanceInMiles"])

        return jsonify({
            "flatRoute":  flat,
            "shortRoute": short,
            "allRoutes":  filtered[:6]
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
