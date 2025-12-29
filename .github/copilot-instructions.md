# Azure Storage Lister - AI Agent Instructions

## Project Overview

This is an **Azure Functions Python application** that provides HTTP endpoints to interact with Azure Blob Storage. Two primary workflows exist:

1. **List blobs** in a container (`list_files` endpoint)
2. **Style images** with AI transformations and backup originals (`style_images` endpoint)

## Architecture & Data Flow

### Core Pattern: Storage-Centric

- All operations use **Azure Blob Storage** as the single source of truth
- Connection strings: prioritize `TARGET_STORAGE_CONNECTION_STRING` environment variable, fall back to `AzureWebJobsStorage`
- Default container: `file-container` if not specified in request

### Rate Limiting

- **Built-in per-instance in-memory limiter**: 100 requests per 60 seconds using `deque`
- Located in [function_app.py](function_app.py#L14-L21)
- Returns HTTP 429 when exceeded
- **Important**: This is single-instance only; multi-instance deployments need distributed rate limiting

### Image Styling Pipeline (`style_images` endpoint)

Sequence: Download → Backup Original → Apply Styles → Upload Results

1. **Source Detection**: Lists blobs in `{source_folder}/` (default: `source/`), filters `.jpg/.jpeg/.png`
2. **Backup**: Saves original to `{output_folder}/original/{filename}`
3. **Style Application**:
   - Iterates 4 predefined styles: geometric_3d, watercolor, cyberpunk, anime (see [PREDEFINED_STYLES](function_app.py#L88-L101))
   - For each style not yet processed (checked via `blob_client.exists()`):
     - POST to external image API: `endpoint_url` with multipart form (`file` + `prompt` + `api-key` header)
     - Expects HTTP 200 with image bytes in response body
     - Saves result to `{output_folder}/{style_name}/{filename}`
   - Skips already-processed files (incremental, no overwrites)
   - Missing API config (`AZURE_API_KEY` or `AZURE_ENDPOINT_URL`) → file marked failed with "API Config Missing"
4. **Error Handling**: Returns per-file failure details instead of failing entire batch
   - Response includes `processed`, `failed` (with error messages), and `skipped` arrays
   - Blob download/upload failures don't stop other files

### Optional (for image styling)

- `AZURE_API_KEY`: API key for image generation endpoint
- `AZURE_ENDPOINT_URL`: Image generation service endpoint
- If missing, image operations report "API Config Missing" per file

## Request Patterns

### list_files Endpoint

```
GET /api/list_files?container=my-container
```

Response: JSON array of blob names. Falls back to `file-container` if no container specified.

### style_images Endpoint

```
POST /api/style_images
Content-Type: application/json

{
  "container": "file-container",     // optional, default: "file-container"
  "source_folder": "source",         // optional, default: "source"
  "output_folder": "output"          // optional, default: "output"
}
```

Response: JSON with `processed`, `failed`, `skipped` arrays; includes error details per file.

## Development Workflow

### Setup

1. `pip install -r requirements.txt` (or use task: "pip install (functions)")
2. Set environment variables in [local.settings.json](local.settings.json)
3. `func host start` (or use task: "func: host start") - runs locally on `http://localhost:7071`

### Key Dependencies

- `azure-functions`: Azure Functions SDK
- `azure-storage-blob`: Blob Storage client
- `requests`: HTTP library for API calls

### Deployment Pipeline

Automated CI/CD via [.github/workflows/deploy.yml](.github/workflows/deploy.yml):

- **Trigger**: Push to `master` branch
- **Steps**:
  1. Checkout code
  2. Setup Python 3.10 environment
  3. Install dependencies to `.python_packages/lib/site-packages`
  4. Authenticate to Azure via `AZURE_CREDENTIALS` secret
  5. Deploy to Azure Function App: `func-storage-lister-9285` using `Azure/functions-action`
- **Key Variables** (update in workflow file):
  - `AZURE_FUNCTIONAPP_NAME`: Target Function App name
  - `PYTHON_VERSION`: Runtime version (3.10)
- **Prerequisites**: `AZURE_CREDENTIALS` secret must be set in repo (Azure service principal JSON)

## Code Patterns & Conventions

### Error Responses

- Use `func.HttpResponse(message, status_code=N)` for consistency
- API errors → HTTP 500 with exception string
- Missing config → HTTP 500
- Rate limit → HTTP 429
- Missing container → HTTP 404 (style_images only)

### Request Parsing Priority

1. Query parameters (`req.params.get()`)
2. JSON body (`req.get_json()`)
3. Default values (e.g., `"file-container"`)

### Blob Operations

- Always use `container_client.get_blob_client(blob_name)` for individual blobs
- Check existence with `target_client.exists()` before upload (avoids unnecessary work)
- Use `overwrite=True` for uploads to handle retries gracefully

### Logging

- Use `logging.info()` and `logging.warning()` (routed to Application Insights via [host.json](host.json))
- Info: Request processing, status updates
- Warning: Missing API config (non-fatal)

## Adding New Functionality

- New endpoints: Add `@app.route(route="endpoint_name")` function with `rate_limiting` check as first step
- New styles: Add to `PREDEFINED_STYLES` list (name + prompt_text only)
- Storage operations: Reuse `connect_str` pattern (TARGET_STORAGE_CONNECTION_STRING priority)
