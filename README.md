# ARNIX Video Engine

Independent video-source resolver and HLS gateway built with FastAPI.

## Current implementation

- REST API and health endpoint.
- Embed resolution through the MIT-licensed `anime-dl-core==0.5.1` library.
- Kodik and the other player adapters supported by that library, when a valid embed URL is supplied.
- Alloha catalog search through the library's `Alloha` helper.
- Signed HLS gateway that rewrites relative playlist segments and URI attributes.
- Docker image and GitHub Actions CI.

## Important provider limitation

Alloha is a catalog source, not a direct-stream resolver in `anime-dl-core`. Its documented integration returns metadata and an iframe URL; the library explicitly says it does not expose Alloha's direct video URLs. This project therefore does not claim direct HLS extraction from Alloha. The Alloha iframe can be used by a compatible client. No DRM, authentication, geo, or paywall bypass is implemented.

HDRezka does not currently have a verified adapter in the bundled library. It is listed as a planned adapter, not a working resolver. Provider modules must be implemented and tested against lawful, publicly accessible embed URLs before being marked supported.

## Run locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs`.

## API

- `GET /health`
- `GET /api/v1/providers`
- `POST /api/v1/resolve` with JSON `{"url":"https://...embed..."}`
- `GET /api/v1/alloha/search?q=...`
- `GET /api/v1/gateway/{signed-token}` (tokens are generated only by the resolver)

## Configuration

Set `APP_SECRET` to a long random value in the deployment environment. Set `ALLOHA_TOKEN` only if you have a valid token. Never commit secrets.

## Deploy

Build and run the Dockerfile on a host that supports long-running containers and streaming HTTP responses. GitHub Actions runs tests and validates the Docker build; GitHub Actions itself is not a permanent web host.

## License

Project code: MIT. Third-party libraries retain their own licenses; see their upstream repositories.
