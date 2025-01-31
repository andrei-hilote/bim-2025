import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Any, List

import rtree
from shapely.geometry import shape, Point


class SpatialDataStore:
    def __init__(self, db_path: str = "flood_data.db", cache_dir: str = "cache"):
        self.db_path = db_path

        self.index_path = Path("spatial_index")
        self.index_path.mkdir(exist_ok=True)
        self.spatial_index = rtree.index.Index(str(self.index_path / "rtree"))

        # Initialize database
        self._init_db()

    def _init_db(self):
        with self._get_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS waterways (
                    id INTEGER PRIMARY KEY,
                    waterway_type TEXT,
                    properties JSON,
                    geometry JSON
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS flooding_layers (
                    id INTEGER PRIMARY KEY,
                    layer_type TEXT,
                    properties JSON,
                    geometry JSON
                )
            """)

            # Create indices
            conn.execute("CREATE INDEX IF NOT EXISTS idx_waterway_type ON waterways(waterway_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_layer_type ON flooding_layers(layer_type)")

    @contextmanager
    def _get_db(self):
        conn = sqlite3.connect(self.db_path)
        # conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def store_waterway_data(self, geojson_data: Dict[str, Any]):
        """Store waterway data efficiently"""
        features = geojson_data['features']

        with self._get_db() as conn:
            for idx, feature in enumerate(features):
                waterway_type = feature['properties'].get('waterway', 'other')

                # Store in database
                conn.execute(
                    "INSERT INTO waterways (waterway_type, properties, geometry) VALUES (?, ?, ?)",
                    (
                        waterway_type,
                        json.dumps(feature['properties']),
                        json.dumps(feature['geometry'])
                    )
                )

                # Add to spatial index
                geom = shape(feature['geometry'])
                self.spatial_index.insert(idx, geom.bounds)

            conn.commit()


    async def store_flooding_data(self, geojson_data: Dict[str, Any]):
        """Store flooding data efficiently"""
        features = geojson_data['features']
        layer_mappings = {
            'P01_REF_Buildings': 'buildings',
            'P01_REF_Transportation': 'transportation',
            'P02_LULC': 'landuse',
            'P03_MOD_Inundation': 'inundation'
        }

        with self._get_db() as conn:
            for idx, feature in enumerate(features):
                source_file = feature['properties'].get('sourceFile', '')
                layer_type = next((type_ for pattern, type_ in layer_mappings.items()
                                   if pattern in source_file), 'other')

                # Store in database
                conn.execute(
                    "INSERT INTO flooding_layers (layer_type, properties, geometry) VALUES (?, ?, ?)",
                    (
                        layer_type,
                        json.dumps(feature['properties']),
                        json.dumps(feature['geometry'])
                    )
                )

                # Add to spatial index
                geom = shape(feature['geometry'])
                self.spatial_index.insert(idx + 1000000, geom.bounds)  # Offset to avoid collision with waterway indices


    def get_waterway(self):
        with self._get_db() as conn:

            geometries = []
            rows = conn.execute("SELECT * FROM waterways").fetchall()

            for row in rows:
                geometries.append(json.loads(row[3]))

            with open("geometry.html", "w") as file:
                json.dump(geometries, file, indent=4)

    def find_nearby_waterways(self, point: Point, radius: float) -> List[Dict[str, Any]]:
        """Find waterways near the given point using spatial index"""

        point_shape = Point(point.lng, point.lat)
        buffer_degrees = radius / 111000
        bbox = (
            point.lng - buffer_degrees,
            point.lat - buffer_degrees,
            point.lng + buffer_degrees,
            point.lat + buffer_degrees
        )

        nearby_waterways = []

        # Use spatial index to get potential matches
        potential_matches = list(self.spatial_index.intersection(bbox))

        with self._get_db() as conn:
            for idx in potential_matches:
                if idx >= 1000000:  # Skip flooding layer indices
                    continue

                row = conn.execute(
                    "SELECT * FROM waterways WHERE rowid = ?",
                    (idx + 1,)  # SQLite rowid starts at 1
                ).fetchone()

                if not row:
                    continue

                feature_shape = shape(json.loads(row[3]))
                if feature_shape.distance(point_shape) <= buffer_degrees:
                    properties = json.loads(row[2])
                    nearby_waterways.append({
                        "type": row[1],
                        "name": properties.get('name', 'unnamed'),
                        "distance": feature_shape.distance(point_shape) * 111000,
                        "properties": properties
                    })


        return nearby_waterways

    def get_flooding_data(self, point: Point, radius: float) -> Dict[str, Any]:

        point_shape = Point(point.lng, point.lat)
        buffer_degrees = radius / 111000
        bbox = (
            point.lng - buffer_degrees,
            point.lat - buffer_degrees,
            point.lng + buffer_degrees,
            point.lat + buffer_degrees
        )

        flooding_data = {
            "buildings_in_area": 0,
            "transportation_features": 0,
            "landuse_areas": 0,
            "known_inundation_areas": 0,
            "details": {}
        }

        # Use spatial index to get potential matches
        potential_matches = list(self.spatial_index.intersection(bbox))

        with self._get_db() as conn:
            for idx in potential_matches:
                if idx < 1000000:  # Skip waterway indices
                    continue

                row = conn.execute(
                    "SELECT * FROM flooding_layers WHERE rowid = ?",
                    (idx - 1000000 + 1,)  # Adjust index and account for SQLite rowid starting at 1
                ).fetchone()

                if not row:
                    continue

                feature_shape = shape(json.loads(row['geometry']))
                if feature_shape.distance(point_shape) <= buffer_degrees:
                    layer_type = row['layer_type']
                    properties = json.loads(row['properties'])

                    if layer_type not in flooding_data["details"]:
                        flooding_data["details"][layer_type] = []

                    flooding_data["details"][layer_type].append({
                        "type": properties.get('type', layer_type),
                        "distance": feature_shape.distance(point_shape) * 111000,
                        "properties": properties
                    })

                    flooding_data[f"{layer_type}_in_area"] = len(flooding_data["details"][layer_type])

        return flooding_data
