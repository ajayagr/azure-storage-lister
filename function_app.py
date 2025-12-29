import azure.functions as func
import logging
import os
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

@app.route(route="list_files")
def list_files(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    # Get connection string from environment variables
    connect_str = os.getenv('AzureWebJobsStorage')
    container_name = req.params.get('container')

    if not connect_str:
        return func.HttpResponse(
            "AzureWebJobsStorage environment variable not set.",
            status_code=500
        )
    
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
