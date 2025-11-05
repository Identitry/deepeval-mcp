# Deepeval MCP Bridge

Expose the existing `deepeval-wrapper` evaluation logic through a Model Context Protocol (MCP) compatible FastAPI service.

## Acknowledgements

This project builds upon the excellent work by [theaiautomators](https://github.com/theaiautomators) and their [deepeval-wrapper](https://github.com/theaiautomators/deepeval-wrapper) project. We've extended it with MCP compatibility and fixed a critical ASCII encoding bug in the OpenAI SDK's httpx integration to ensure robust Unicode support.

## Features

### MCP API (Wrapped Responses)
- `POST /mcp/evaluate` – forwards evaluation payloads to the wrapper and returns MCP-formatted results.
- `GET /mcp/metrics` – lists the metrics available to the wrapper.
- `GET /mcp/metrics/categories` – get metrics organized by category.
- `GET /mcp/metrics/{metric_type}` – get detailed information about a specific metric.

### Direct Wrapper Access
- All deepeval-wrapper endpoints are available at `/wrapper/*`
- Interactive API docs at `/wrapper/docs`
- Includes synchronous endpoints (`/wrapper/evaluate/`, `/wrapper/metrics/`) and asynchronous job management (`/wrapper/jobs/*`)

### Additional Features
- In-process ASGI communication (no network overhead between MCP server and wrapper)
- Health probes at `/health` and `/healthz`
- API discovery endpoint at `/` with comprehensive documentation
- Docker image ready for local development or deployment
- Fancy startup banner with service information

## Prerequisites
- Docker (24.x or newer recommended)
- At least one LLM API key (OpenAI, Anthropic, or Google) for running evaluations
- The `deepeval-wrapper` package is automatically embedded during Docker build

## Setup

### 1. Configure Environment Variables

Copy `.env.example` to `.env` and populate the required secrets:
```bash
cp .env.example .env
```

Edit the `.env` file and configure:

#### Required: LLM API Keys
At least **one** of these is required for DeepEval to run evaluations:
- `OPENAI_API_KEY` - OpenAI API key (recommended) - [Get one here](https://platform.openai.com/api-keys)
- `ANTHROPIC_API_KEY` - Anthropic Claude API key - [Get one here](https://console.anthropic.com/)
- `GOOGLE_API_KEY` - Google API key - [Get one here](https://console.cloud.google.com/)

#### Optional: Authentication

**API_KEYS - Unified Authentication:**
- `API_KEYS` - Protects **both** `/mcp/*` and `/wrapper/*` endpoints with `X-API-Key` header validation
- Supports multiple keys as comma-separated list: `key1,key2,key3`
- Leave blank or unset to disable authentication (**NOT recommended for production!**)

**Security Note:**
- If `API_KEYS` is **not set**, authentication is **disabled** for both endpoint groups
- The wrapper's insecure default `deepeval-default-key` is automatically overridden with empty string
- This prevents the publicly-known default key from being active

**Examples:**
```bash
# Single key (simple setup)
API_KEYS=my-secret-key-123

# Multiple keys (allows key rotation and multiple clients)
API_KEYS=client-1-key,client-2-key,rotation-key

# Disabled (leave blank or omit - not recommended for production!)
# API_KEYS=
```

**Benefits of multiple keys:**
- Issue different keys to different clients for access tracking
- Rotate keys without downtime (add new key, migrate clients, remove old key)
- Revoke individual client access without affecting others

#### Optional: Advanced Settings

These typically don't need to be changed:
- `DEEPEVAL_WRAPPER_IMPORT_PATH` - Module import path (default: `app.main`)
- `DEEPEVAL_WRAPPER_ASGI_TARGET` - ASGI app target (default: auto-detected)
- `DEEPEVAL_HTTP_TIMEOUT` - Timeout for wrapper calls in seconds (default: `30`)

### 2. Build & Run
```bash
docker build -t deepeval-mcp .
docker run --env-file .env -p 8000:8000 deepeval-mcp
```

The service will be available at `http://localhost:8000`.

**Available endpoints:**
- `/` - API discovery with comprehensive documentation
- `/docs` - MCP API interactive Swagger UI
- `/wrapper/docs` - Direct wrapper API interactive Swagger UI

## Usage

### Example Request

The MCP server forwards requests to the deepeval-wrapper, which expects structured test case data:

```bash
curl -X POST "http://localhost:8000/mcp/evaluate" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key-here" \
  -d '{
        "test_case": {
          "input": "What is the capital of France?",
          "actual_output": "Paris is the capital of France."
        },
        "metrics": [
          {"metric_type": "answer_relevancy"}
        ]
      }'
```

**Note:** If `API_KEYS` is not set, you can omit the `X-API-Key` header (authentication is disabled).

**Note**: The `metric_type` field is required. Common values: `answer_relevancy`, `faithfulness`, `contextual_relevancy`, `hallucination`, `bias`, `toxicity`, etc.

### Sample Response
The response is wrapped in an MCP envelope:
```json
{
  "type": "mcp.result",
  "timestamp": "2024-01-01T00:00:00.000000+00:00",
  "provider": "deepeval",
  "request_id": "uuid-here",
  "data": {
    "test_case": {...},
    "results": [
      {
        "metric": "answer_relevancy",
        "score": 0.95,
        "reason": "...",
        "success": true
      }
    ]
  }
}
```

**Note**: The request format matches the [deepeval-wrapper API](https://github.com/theaiautomators/deepeval-wrapper). See their documentation for available metrics and test case formats.

### Accessing Wrapper Endpoints Directly

The wrapper's full API is available at `/wrapper/*`:

```bash
# List available metrics
curl -X GET "http://localhost:8000/wrapper/metrics/" \
  -H "X-API-Key: your-api-key-here"

# Direct evaluation (without MCP wrapper)
curl -X POST "http://localhost:8000/wrapper/evaluate/" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key-here" \
  -d '{
        "test_case": {
          "input": "What is the capital of France?",
          "actual_output": "Paris is the capital of France."
        },
        "metrics": [
          {"metric_type": "answer_relevancy"}
        ]
      }'
```

**Note**: Both `/mcp/*` and `/wrapper/*` endpoints use the same `API_KEYS` authentication. If `API_KEYS` is not set, you can omit the `X-API-Key` header.

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | One of three* | - | OpenAI API key for GPT models |
| `ANTHROPIC_API_KEY` | One of three* | - | Anthropic API key for Claude models |
| `GOOGLE_API_KEY` | One of three* | - | Google API key for Gemini models |
| `API_KEYS` | No | Empty (auth disabled) | Comma-separated API keys protecting both `/mcp/*` and `/wrapper/*` endpoints |
| `DEEPEVAL_WRAPPER_IMPORT_PATH` | No | `app.main` | Python module path for wrapper |
| `DEEPEVAL_WRAPPER_ASGI_TARGET` | No | Auto-detected | ASGI app import path |
| `DEEPEVAL_HTTP_TIMEOUT` | No | `30` | Timeout for wrapper calls (seconds) |

\* At least one LLM API key is required

**Security Notes:**
- If `API_KEYS` is not set, authentication is **disabled** (wrapper's `deepeval-default-key` is overridden with empty string)
- Multiple keys are supported: `API_KEYS=key1,key2,key3`
- Use strong, randomly-generated keys in production

## Development Notes
- The default Docker build installs `git` for fetching the embedded wrapper; remove it if you vendor the code.
- For long-running deployments consider setting `UVICORN_WORKERS` and other runtime options via environment variables.
- The server includes a `sitecustomize.py` that fixes UTF-8 encoding issues with the OpenAI SDK and httpx library.
- Authentication is optional but **strongly recommended** for production deployments.
- The wrapper's insecure default `deepeval-default-key` is automatically overridden with empty string if `API_KEYS` is not set.

## Continuous Integration

The repository includes a GitHub Actions workflow (`.github/workflows/build.yaml`) that automatically builds and publishes Docker images to GitHub Container Registry (GHCR).

### Workflow Features

- **Automatic Version Detection**: Checks PyPI daily for new DeepEval releases
- **Smart Build Logic**: Only builds when a new version is detected (saves CI minutes)
- **Multi-Architecture Support**: Builds for both `linux/amd64` and `linux/arm64`
- **Automated Testing**: Runs smoke tests on published images
- **Auto-Update**: Automatically updates `requirements.txt` and commits the change
- **Manual Trigger**: Can be triggered manually via `workflow_dispatch`

### Triggers

1. **Daily Scheduled**: Runs at 3 AM UTC every day
2. **Manual**: Via GitHub Actions "Run workflow" button

### Published Images

Images are published to:
```
ghcr.io/identitry/deepeval-mcp:latest
ghcr.io/identitry/deepeval-mcp:<version>
```

Pull the latest:
```bash
docker pull ghcr.io/identitry/deepeval-mcp:latest
```

Or a specific version:
```bash
docker pull ghcr.io/identitry/deepeval-mcp:3.7.0
```
