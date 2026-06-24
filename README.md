Geospatial SAM3 Segmentation API
This API service handles the upload, visualization, and AI-powered segmentation of raw TIFF/GeoTIFF images. It provides a seamless pipeline for frontends to render geospatial imagery on maps (e.g., using Leaflet and GeoRaster) and trigger asynchronous background segmentation using the SAM3 model based on user-defined Areas of Interest (AOIs).

🚀 Typical Workflow
Upload: Submit a .tiff or .geotiff file to receive an image_id.

Visualize: Fetch the visualization URL for the image_id to render the image on your map frontend.

Segment: Send a user-drawn Area of Interest (AOI) as a GeoJSON Polygon to trigger SAM3 processing, receiving a task_id in return.

Poll: Poll the task status using the task_id until completion to retrieve the download/render URLs for the generated semantic masks.

📖 API Reference
1. Upload TIFF Image
Uploads a raw TIFF/GeoTIFF image to the server and registers it for processing.

URL: /api/v1/images/upload

Method: POST

Content-Type: multipart/form-data

Request Parameters:

file: The raw TIFF/GeoTIFF file.

2. Get Map Visualization URL
Retrieves the direct URL of the uploaded image so the frontend can render it on a map.

URL: /api/v1/images/<image_id>/visualization

Method: GET

Content-Type: application/json

Path Parameters:

image_id (string): The unique ID returned from the upload step.

3. Trigger AI Segmentation
Submits a user-drawn Area of Interest (AOI) to the backend to begin background SAM3 processing.

URL: /api/v1/images/<image_id>/segment

Method: POST

Content-Type: application/json

Path Parameters:

image_id (string): The unique ID of the target image.

Request Body:
Expects a valid GeoJSON Polygon representing the bounding box or area the user drew on the map.

JSON
{
  "type": "Feature",
  "geometry": {
    "type": "Polygon",
    "coordinates": [
      [
        [100.0, 0.0],
        [101.0, 0.0],
        [101.0, 1.0],
        [100.0, 1.0],
        [100.0, 0.0]
      ]
    ]
  }
}
4. Poll Task Status & Retrieve Results
Used by the frontend to poll the background AI process. Once the status hits finished, it provides the URLs for the generated semantic masks.

URL: /api/v1/tasks/<task_id>/status

Method: GET

Content-Type: application/json

Path Parameters:

task_id (string): The background task ID returned from the segmentation trigger.

Responses:

Response 1: Processing (200 OK)

JSON
{
  "task_id": "abc-123",
  "status": "processing"
}
Response 2: Completed (200 OK)
When the status equals finished, a result object is appended containing the direct download/render URLs for the generated masks.

JSON
{
  "task_id": "abc-123",
  "status": "finished",
  "result": {
    "mask_url": "https://<your-server>/media/masks/mask_abc123.png",
    "geojson_url": "https://<your-server>/media/vectors/poly_abc123.geojson"
  }
}
Response 3: Failed (200 OK)
If the AI model crashes or the GeoJSON is mathematically invalid, the status will flip to failed.

JSON
{
  "task_id": "abc-123",
  "status": "failed",
  "error": "Mathematical intersection error in provided GeoJSON."
}
