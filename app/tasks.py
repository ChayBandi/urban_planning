import os
import tempfile
import shutil
import torch
import rasterio
from rasterio.mask import mask
from rasterio.windows import Window
from rasterio.merge import merge
from rasterio.features import shapes
import pyproj
from shapely.geometry import shape, Polygon, MultiPolygon
from shapely.ops import transform
import numpy as np
import cv2
import geopandas as gpd

try:
    from samgeo.samgeo3 import SamGeo3
except ImportError:
    from samgeo3 import SamGeo3

try:
    from buildingregulariser import regularize_geodataframe
except ImportError:
    print("WARNING: buildingregulariser not installed.")

DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
TEXT_PROMPTS = ["building", "road", "vegetation"]

# ==========================================
# 🎛️ THE TWEAK DASHBOARD
# ==========================================
KERNEL_SIZE = 5
PRE_SIMPLIFY_TOLERANCE = 2.5 
FORCE_PURE_RECTANGLES = True
FORCE_METRIC_CRS = True 
MIN_BUILDING_AREA_SQM = 20.0
REMOVE_INTERNAL_HOLES = True
# ==========================================

def update_task_status(app, task_id, status, message):
    with app.app_context():
        from .models import db, ImageTask
        task = ImageTask.query.get(task_id)
        if task:
            task.status = status
            task.message = message
            db.session.commit()

def remove_holes(geom):
    if geom.geom_type == 'Polygon':
        return Polygon(geom.exterior)
    elif geom.geom_type == 'MultiPolygon':
        return MultiPolygon([Polygon(p.exterior) for p in geom.geoms])
    return geom

def vectorize_and_regularize_mask(input_tif, output_geojson):
    """Converts raw SAM3 mask into regularized GeoJSON mapped for Web GIS."""
    with rasterio.open(input_tif) as src:
        mask_data = src.read(1)
        transform_data = src.transform
        crs = src.crs

    mask_data = mask_data.astype(np.uint8)
    if mask_data.max() == 1:
        mask_data = mask_data * 255

    kernel = np.ones((KERNEL_SIZE, KERNEL_SIZE), np.uint8)
    cleaned_mask = cv2.morphologyEx(mask_data, cv2.MORPH_CLOSE, kernel)
    cleaned_mask = cv2.morphologyEx(cleaned_mask, cv2.MORPH_OPEN, kernel)

    building_pixels = cleaned_mask > 0
    extracted_shapes = shapes(cleaned_mask, mask=building_pixels, transform=transform_data)
    
    raw_geometries = [shape(geom_dict) for geom_dict, value in extracted_shapes]
    
    if not raw_geometries:
        return False

    gdf = gpd.GeoDataFrame(geometry=raw_geometries, crs=crs)
    original_crs = gdf.crs

    if FORCE_METRIC_CRS:
        gdf = gdf.to_crs(epsg=3857)
        
    if REMOVE_INTERNAL_HOLES:
        gdf.geometry = gdf.geometry.apply(remove_holes)

    if MIN_BUILDING_AREA_SQM > 0:
        gdf = gdf[gdf.geometry.area >= MIN_BUILDING_AREA_SQM]

    if FORCE_PURE_RECTANGLES:
        gdf.geometry = gdf.geometry.apply(lambda geom: geom.minimum_rotated_rectangle)
    else:
        if PRE_SIMPLIFY_TOLERANCE > 0:
            gdf.geometry = gdf.geometry.simplify(tolerance=PRE_SIMPLIFY_TOLERANCE, preserve_topology=True)
        try:
            gdf = regularize_geodataframe(gdf)
        except Exception as e:
            print(f"Regularization skipped/failed: {e}")

    # THE FIX: Always project the final GeoJSON to standard GPS coordinates for Leaflet
    try:
        gdf = gdf.to_crs(epsg=4326)
    except Exception as e:
        print(f"Warning: Could not project to EPSG:4326 - {e}")

    gdf.to_file(output_geojson, driver="GeoJSON")
    return True

def validate_tiff_task(app, task_id, image_id, filepath):
    update_task_status(app, task_id, 'processing', 'Validating TIFF file...')
    try:
        with rasterio.open(filepath) as src:
            width = src.width
            height = src.height
        update_task_status(app, task_id, 'completed', f"TIFF validated successfully ({width}x{height})")
    except Exception as e:
        update_task_status(app, task_id, 'failed', f'Invalid TIFF: {str(e)}')

def run_sam_segmentation(app, task_id, image_id, aoi_geojson):
    update_task_status(app, task_id, 'segmenting', 'Initializing SAM3 and clipping AOI...')
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    uploads_dir = os.path.join(base_dir, 'uploads')
    outputs_dir = os.path.join(base_dir, 'outputs')
    os.makedirs(outputs_dir, exist_ok=True)
    
    original_tiff = None
    for f in os.listdir(uploads_dir):
        if f.startswith(image_id):
            original_tiff = os.path.join(uploads_dir, f)
            break
            
    if not original_tiff:
        update_task_status(app, task_id, 'failed', f"Original TIFF for {image_id} not found.")
        return

    temp_dir = tempfile.mkdtemp(prefix="sam3_task_")
    cropped_tiff_path = os.path.join(temp_dir, "cropped_input.tif")
    
    try:
        # A. GEOSPATIAL CLIPPING
        geom_4326 = shape(aoi_geojson['geometry'])
        with rasterio.open(original_tiff) as src:
            src_crs = src.crs
            project = pyproj.Transformer.from_crs(pyproj.CRS("EPSG:4326"), src_crs, always_xy=True).transform
            geom_projected = transform(project, geom_4326)
            
            out_image, out_transform = mask(src, [geom_projected], crop=True)
            out_meta = src.meta.copy()
            out_meta.update({
                "driver": "GTiff", "height": out_image.shape[1],
                "width": out_image.shape[2], "transform": out_transform
            })
            with rasterio.open(cropped_tiff_path, "w", **out_meta) as dest:
                dest.write(out_image)

        # B. SAM INFERENCE
        update_task_status(app, task_id, 'segmenting', 'Running SAM3 Inference...')
        sam3 = SamGeo3(model_id="facebook/sam3", device=DEVICE, enable_inst_interactivity=False)
        mask_tile_paths = {prompt: [] for prompt in TEXT_PROMPTS}
        TILE_SIZE = 1024
        OVERLAP = 256
        STRIDE = TILE_SIZE - OVERLAP

        with rasterio.open(cropped_tiff_path) as src:
            meta = src.meta.copy()
            width, height = src.width, src.height

            for col_off in range(0, width, STRIDE):
                for row_off in range(0, height, STRIDE):
                    window = Window(col_off, row_off, TILE_SIZE, TILE_SIZE).intersection(Window(0, 0, width, height))
                    tile_data = src.read(window=window)
                    
                    if not tile_data.any(): continue
                        
                    tile_meta = meta.copy()
                    tile_meta.update({"height": window.height, "width": window.width, "transform": src.window_transform(window)})
                    
                    tile_img_path = os.path.join(temp_dir, f"tile_{col_off}_{row_off}.tif")
                    with rasterio.open(tile_img_path, "w", **tile_meta) as dest:
                        dest.write(tile_data)

                    sam3.set_image(tile_img_path)
                    
                    for prompt in TEXT_PROMPTS:
                        tile_mask_path = os.path.join(temp_dir, f"mask_{prompt}_{col_off}_{row_off}.tif")
                        try:
                            sam3.generate_masks(prompt, confidence_threshold=0.5)
                            sam3.save_masks(tile_mask_path, unique=False)
                            if os.path.exists(tile_mask_path):
                                mask_tile_paths[prompt].append(tile_mask_path)
                        except Exception:
                            pass

        # C. MERGING & VECTORIZING OUTPUTS
        update_task_status(app, task_id, 'segmenting', 'Vectorizing and regularizing polygons...')
        with rasterio.open(cropped_tiff_path) as src:
            base_meta = src.meta.copy()

        for prompt in TEXT_PROMPTS:
            paths = mask_tile_paths[prompt]
            if not paths: continue
                
            src_files = [rasterio.open(p) for p in paths]
            mosaic, out_trans = merge(src_files, method='max')
            for f in src_files: f.close()

            out_meta = base_meta.copy()
            out_meta.update({
                "count": 1, "dtype": rasterio.uint8, "compress": "deflate", "nodata": 0,
                "height": mosaic.shape[1], "width": mosaic.shape[2], "transform": out_trans
            })

            temp_final_tiff = os.path.join(temp_dir, f"temp_mask_{prompt}.tif")
            with rasterio.open(temp_final_tiff, "w", **out_meta) as dest:
                dest.write(mosaic)

            final_geojson_path = os.path.join(outputs_dir, f"mask_{image_id}_{prompt}.geojson")
            vectorize_and_regularize_mask(temp_final_tiff, final_geojson_path)

        update_task_status(app, task_id, 'finished', 'Segmentation complete!')

    except Exception as e:
        update_task_status(app, task_id, 'failed', f'Error: {str(e)}')
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)