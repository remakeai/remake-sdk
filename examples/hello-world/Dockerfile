FROM python:3.11-slim

LABEL app.id="com.example.hello-world"
LABEL app.version="1.0.0"
LABEL app.name="Hello World"

WORKDIR /app

# Copy app files
COPY app.py .
COPY manifest.json .

# Run the app
CMD ["python", "-u", "app.py"]
