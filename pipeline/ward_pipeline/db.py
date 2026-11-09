import geopandas as gpd
from sqlalchemy import Engine, create_engine, text

from .config import DATABASE_URL


def engine() -> Engine:
    return create_engine(DATABASE_URL)


def upsert(eng: Engine, gdf: gpd.GeoDataFrame, table: str, key: str) -> int:
    """Insert rows, replacing any with the same key. Geometry column is `geom`."""
    if gdf.empty:
        return 0
    staging = f"_staging_{table}"
    gdf = gdf.rename_geometry("geom")
    cols = list(gdf.columns)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != key)
    with eng.begin() as conn:
        gdf.to_postgis(staging, conn, if_exists="replace", index=False)
        conn.execute(
            text(
                f"INSERT INTO {table} ({', '.join(cols)}) "
                f"SELECT {', '.join(_cast(c, table) for c in cols)} FROM {staging} "
                f"ON CONFLICT ({key}) DO UPDATE SET {updates}"
            )
        )
        conn.execute(text(f"DROP TABLE {staging}"))
    return len(gdf)


def replace_in_area(eng: Engine, gdf: gpd.GeoDataFrame, table: str, area_wkt: str) -> int:
    """For tables without a natural key: drop rows touching the area, then insert."""
    gdf = gdf.rename_geometry("geom")
    with eng.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {table} WHERE ST_Intersects(geom, ST_GeomFromText(:a, 4326))"),
            {"a": area_wkt},
        )
        if not gdf.empty:
            gdf.to_postgis(table, conn, if_exists="append", index=False)
    return len(gdf)


# JSONB and array columns arrive from pandas as text; cast them on the way in.
_CASTS = {
    "census_areas": {
        "age_dist": "jsonb",
        "housing_dist": "jsonb",
        "occupation_dist": "jsonb",
        "language_dist": "jsonb",
    },
    "transit_stops": {"routes": "text[]"},
}


def _cast(col: str, table: str) -> str:
    cast = _CASTS.get(table, {}).get(col)
    return f"{col}::{cast}" if cast else col
