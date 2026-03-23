# App Dashboard - Sample app with web UI
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    python-socketio[client] \
    aiohttp \
    flask

# Copy SDK (for containerized deployment)
COPY remake_sdk/ /app/remake_sdk/

# Copy app
COPY examples/app-dashboard/app.py /app/

# Expose web server port
EXPOSE 8080

# Run the app
CMD ["python", "app.py"]
