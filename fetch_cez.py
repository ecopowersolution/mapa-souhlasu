#!/usr/bin/env python3
"""Stahne data z CEZ ArcGIS (mapa pro akumulace) a vygeneruje
akumulace_vn.js a akumulace_vvn.js pro mapu souhlasu.

Zdroj (verejne, bez klice, zdarma):
  https://geoportal.cezdistribuce.cz/arcgis/rest/services/AKUMUL/akumulace/MapServer
  vrstva 0 = Vysoke napeti (VN), vrstva 1 = Velmi vysoke napeti (VVN)

ID_BARVA: 0 = neni distribucni oblast CEZ (preskakujeme, je pruhledna),
          1 = volna kapacita > 10 MW, 2 = volna <= 10 MW, 3 = omezeni pripojeni.
ArcGIS nepodporuje stránkovani pres resultOffset -> tahame po davkach pres objectIds.
"""
import json
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://geoportal.cezdistribuce.cz/arcgis/rest/services/AKUMUL/akumulace/MapServer"
OFFSET = 0.0015        # zjednoduseni geometrie ve stupnich (~150 m)
PRECISION = 5          # desetinna mista souradnic
BATCH = 200            # kolik objectIds na jeden dotaz (kvuli delce URL)
LAYERS = {
    0: ("akumulace_vn.js", "akumulaceVN", "AKUMULACE_VN.ID_BARVA"),
    1: ("akumulace_vvn.js", "akumulaceVVN", "AKUMULACE_VVN.ID_BARVA"),
}


def get(url):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    return None


def all_ids(layer):
    q = urllib.parse.urlencode({"where": "1=1", "returnIdsOnly": "true", "f": "json"})
    d = get(f"{BASE}/{layer}/query?{q}")
    return d["objectIds"]


def fetch_batch(layer, ids, barva_field):
    q = urllib.parse.urlencode({
        "objectIds": ",".join(map(str, ids)),
        "outFields": barva_field,
        "returnGeometry": "true",
        "outSR": "4326",
        "maxAllowableOffset": OFFSET,
        "geometryPrecision": PRECISION,
        "f": "json",
    })
    return get(f"{BASE}/{layer}/query?{q}")


def rings_to_geojson(rings):
    """Esri rings -> GeoJSON. Vnejsi prstenec (clockwise) = polygon,
    vnitrni (counter-clockwise) = dira. Zjednodusene: kazdy prstenec
    podle znamenka plochy zaradime jako outer/hole a slozime MultiPolygon."""
    polygons = []
    current = None
    for ring in rings:
        area = 0.0
        for i in range(len(ring) - 1):
            x1, y1 = ring[i]
            x2, y2 = ring[i + 1]
            area += x1 * y2 - x2 * y1
        if area < 0:  # clockwise -> vnejsi prstenec (novy polygon)
            if current:
                polygons.append(current)
            current = [ring]
        else:         # counter-clockwise -> dira
            if current:
                current.append(ring)
            else:
                current = [ring]
    if current:
        polygons.append(current)
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def build_layer(layer):
    fname, varname, barva_field = LAYERS[layer]
    ids = all_ids(layer)
    print(f"  vrstva {layer}: {len(ids)} objektu", file=sys.stderr)
    features = []
    for start in range(0, len(ids), BATCH):
        chunk = ids[start:start + BATCH]
        d = fetch_batch(layer, chunk, barva_field)
        for f in d.get("features", []):
            b = f["attributes"].get(barva_field)
            if not b:           # b == 0 nebo None -> neni CEZ oblast, preskocit
                continue
            rings = f.get("geometry", {}).get("rings")
            if not rings:
                continue
            features.append({
                "type": "Feature",
                "properties": {"b": b},
                "geometry": rings_to_geojson(rings),
            })
        print(f"    {min(start + BATCH, len(ids))}/{len(ids)}", file=sys.stderr)
    fc = {"type": "FeatureCollection", "features": features}
    with open(fname, "w", encoding="utf-8") as out:
        out.write(f"var {varname} = ")
        json.dump(fc, out, separators=(",", ":"), ensure_ascii=False)
        out.write(";\n")
    print(f"  -> {fname}: {len(features)} barevnych polygonu", file=sys.stderr)


if __name__ == "__main__":
    print("Stahuji CEZ akumulace...", file=sys.stderr)
    for layer in LAYERS:
        build_layer(layer)
    print("Hotovo.", file=sys.stderr)
