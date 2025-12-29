import azure.functions as func
import logging
import os
import time
from collections import deque
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Simple in-memory rate limiter (per instance)
# Limit: 100 requests per 60 seconds
RATE_LIMIT = 100
WINDOW_SECONDS = 60
request_history = deque()

def is_rate_limited():
    now = time.time()
    # Remove timestamps older than the window
    while request_history and request_history[0] < now - WINDOW_SECONDS:
        request_history.popleft()
    
    if len(request_history) >= RATE_LIMIT:
        return True
    
    request_history.append(now)
    return False

@app.route(route="list_files")
def list_files(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    if is_rate_limited():
        return func.HttpResponse(
            "Rate limit exceeded. Try again later.",
            status_code=429
        )

    # Get connection string from environment variables
    # Priority: TARGET_STORAGE_CONNECTION_STRING > AzureWebJobsStorage
    connect_str = os.getenv('TARGET_STORAGE_CONNECTION_STRING')
    if not connect_str:
        connect_str = os.getenv('AzureWebJobsStorage')
        
    container_name = req.params.get('container')

    if not container_name:
         # Try to get from body
        try:
            req_body = req.get_json()
        except ValueError:
            req_body = None
            
        if req_body:
             container_name = req_body.get('container')

    # Default to file-container if not provided
    if not container_name:
        container_name = "file-container"

    if not connect_str:
        return func.HttpResponse(
            "AzureWebJobsStorage environment variable not set.",
            status_code=500
        )

    try:
        blob_service_client = BlobServiceClient.from_connection_string(connect_str)
        container_client = blob_service_client.get_container_client(container_name)
        
        blob_list = []
        blobs = container_client.list_blobs()
        for blob in blobs:
            blob_list.append(blob.name)
            
        import json
        return func.HttpResponse(
            json.dumps(blob_list),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        return func.HttpResponse(
            f"Error listing files: {str(e)}",
            status_code=500
        )

# Predefined Styles for Image Generation
PREDEFINED_STYLES = [
    {
        "name": "geometric_3d",
        "prompt_text": "Turn this into geometric 3D abstract art, low poly, vibrant colors"
    },
    {
        "name": "watercolor",
        "prompt_text": "Transform into a beautiful watercolor painting"
    },
    {
        "name": "cyberpunk",
        "prompt_text": "Cyberpunk 2077 style, neon lights, futuristic city, high detail"
    },
    {
        "name": "anime",
        "prompt_text": "Anime style, Studio Ghibli inspired, vibrant, detailed"
    }
]

@app.route(route="style_images")
def style_images(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing style_images request.')
    
    if is_rate_limited():
        return func.HttpResponse("Rate limit exceeded.", status_code=429)

    # Input Parsing
    try:
        req_body = req.get_json()
    except ValueError:
        req_body = {}
    
    source_folder = req_body.get('source_folder', 'source')
    output_folder = req_body.get('output_folder', 'output')
    
    # Standard connection string logic
    connect_str = os.getenv('TARGET_STORAGE_CONNECTION_STRING')
    if not connect_str:
        connect_str = os.getenv('AzureWebJobsStorage')
        
    container_name = req_body.get('container', 'file-container')

    if not connect_str:
        return func.HttpResponse("Storage connection string not found.", status_code=500)

    # AI Configuration
    api_key = os.environ.get('AZURE_API_KEY')
    endpoint_url = os.environ.get('AZURE_ENDPOINT_URL')
    
    if not api_key or not endpoint_url:
        logging.warning("AZURE_API_KEY or AZURE_ENDPOINT_URL not set.")
    
    results = {
        "status": "processing",
        "source": f"{container_name}/{source_folder}",
        "processed": [],
        "failed": [],
        "skipped": []
    }

    try:
        import requests
        blob_service_client = BlobServiceClient.from_connection_string(connect_str)
        container_client = blob_service_client.get_container_client(container_name)
        
        if not container_client.exists():
             return func.HttpResponse(f"Container '{container_name}' does not exist.", status_code=404)

        # Iterate Source
        blobs = container_client.list_blobs(name_starts_with=source_folder)
        for blob in blobs:
            if blob.name.endswith('/'): continue
            
            file_name = os.path.basename(blob.name)
            # Basic validation
            if not any(file_name.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png']):
                continue

            try:
                # 1. Download Source
                blob_client = container_client.get_blob_client(blob.name)
                image_data = blob_client.download_blob().readall()
                
                # 2. Backup Original
                # e.g., output/original/file.jpg
                original_blob_name = f"{output_folder}/original/{file_name}".replace('//', '/')
                container_client.upload_blob(name=original_blob_name, data=image_data, overwrite=True)
                
                # 3. Apply Styles
                for style in PREDEFINED_STYLES:
                    style_name = style['name']
                    prompt = style['prompt_text']
                    
                    target_name = f"{output_folder}/{style_name}/{file_name}".replace('//', '/')
                    target_client = container_client.get_blob_client(target_name)
                    
                    # Skip if exists (Simple Incremental)
                    if target_client.exists():
                        results["skipped"].append(target_name)
                        continue
                        
                    if not api_key or not endpoint_url:
                        results["failed"].append({"file": target_name, "error": "API Config Missing"})
                        continue

                    # Call API
                    try:
                        # FLUX-1-PRO / Generic Image Gen Interface
                        # Assumes: POST multipart with 'file' and 'prompt'
                        files = {'file': (file_name, image_data)}
                        data = {'prompt': prompt}
                        # Azure OpenAI uses 'api-key' header for resource keys
                        headers = {'api-key': api_key}
                        
                        resp = requests.post(endpoint_url, files=files, data=data, headers=headers)
                        
                        if resp.status_code == 200:
                            target_client.upload_blob(resp.content, overwrite=True)
                            results["processed"].append(target_name)
                        else:
                            err = f"API {resp.status_code}: {resp.text[:50]}"
                            results["failed"].append({"file": target_name, "error": err})
                            
                    except Exception as api_err:
                        results["failed"].append({"file": target_name, "error": str(api_err)})
                        
            except Exception as blob_err:
                results["failed"].append({"file": blob.name, "error": str(blob_err)})
                
    except Exception as e:
        return func.HttpResponse(f"Server Error: {str(e)}", status_code=500)

    import json
    return func.HttpResponse(json.dumps(results), mimetype="application/json")
