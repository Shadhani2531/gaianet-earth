# GaiaNet Earth backend image.
#
# main.py serves the whole repo as static files (StaticFiles mounted at
# "/", pointed at the project root — see BASE_DIR in main.py), so the
# build context here is the repo root, not just backend/, or the frontend
# (index.html, js/, css/) would 404 once containerized.
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
