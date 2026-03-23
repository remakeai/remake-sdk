FROM python:3.11-slim

LABEL app.id="com.example.robot-chat"
LABEL app.version="1.0.0"
LABEL app.name="Robot Chat"

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir python-socketio[asyncio_client] aiohttp

# Copy SDK (in production, this would be pip install remake-sdk)
COPY --from=sdk /remake-sdk /remake-sdk
ENV PYTHONPATH=/remake-sdk

# Copy app files
COPY app.py .
COPY manifest.json .

# Run the app
CMD ["python", "-u", "app.py"]
