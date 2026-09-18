# Shared image for backend/app.py and src/vehicle_watcher.py - both need
# the same dependencies and the same src/ codebase, they just run different
# entrypoints (set via `command:` in docker-compose.yml).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY src/ src/
COPY render-start.sh .

# Overridden per-service in docker-compose.yml (and by Render's
# dockerCommand for the combined API+watcher service - see render.yaml).
CMD ["python", "backend/app.py"]
