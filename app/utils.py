import os
import rasterio
from shapely.geometry import shape, box

def validate_and_get_tiff_metadata(file_path: str) -> dict:
    if not os.path.exists(file_path):
        raise FileNotFoundError("TIFF file does not exist.")
        
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    
    with rasterio.open(file_path) as src:
        crs = src.crs.to_string() if src.crs else "Unknown"
        width = src.width
        height = src.height
        bands = src.count
        bounds = src.bounds
        wgs_bounds = [bounds.left, bounds.bottom, bounds.right, bounds.top]

    return {
        "file_size_mb": round(file_size_mb, 2),
        "crs": crs,
        "width": width,
        "height": height,
        "bands": bands,
        "bounds": wgs_bounds,
        "is_valid": bands >= 1 and crs != "Unknown"
    }

def verify_aoi_intersection(aoi_geojson: dict, tiff_bounds: list) -> bool:
    try:
        user_aoi_geom = shape(aoi_geojson)
        tiff_geom = box(*tiff_bounds)
        
        if not user_aoi_geom.is_valid:
            return False
            
        return user_aoi_geom.intersects(tiff_geom)
    except Exception:
        return False