# NFCBACKEND — Fly.io deployment

This repository contains a small FastAPI app (`app.py`). These added files prepare it for deployment on Fly.io.

What I added:
- `Dockerfile` — builds the app with uvicorn and installs dependencies.
- `requirements.txt` — Python dependencies.
- `.dockerignore` — excludes secrets and unnecessary files from the image.
- `fly.toml` — sample Fly configuration (replace `app` value before `flyctl deploy`).

Security note
- `firebase-admin.json` is present in the repo. Do not commit service account files to public repositories. For Fly deployments, prefer using `flyctl secrets set` to provide credentials.

Quick deploy steps (example):

1. Install flyctl and log in.
2. (Optional) Rename the app in `fly.toml` or run `flyctl apps create` to pick a name.
3. Set secrets instead of uploading `firebase-admin.json`:

```bash
flyctl secrets set FIRESTORE_DISABLED=1
# or, if you need firestore enabled, set up a secure credential and set GOOGLE_APPLICATION_CREDENTIALS accordingly
```

4. Deploy:

```bash
flyctl deploy
```

If you want to test locally with Docker:

```bash
# build
docker build -t nfcbackend:local .
# run
docker run --rm -p 8080:8080 -e FIRESTORE_DISABLED=1 nfcbackend:local
```
