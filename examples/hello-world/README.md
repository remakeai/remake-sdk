# Hello World App

A simple test app for the Remake runtime.

## Build

```bash
cd ~/remake-sdk/examples/hello-world
podman build -t hello-world-app .
```

## Test with Runtime

```bash
# Option 1: Install and launch via CLI
remake app install com.example.hello-world --image localhost/hello-world-app:latest
remake app launch com.example.hello-world --local

# Option 2: Direct launch (without installing)
remake app launch hello-world --local --image localhost/hello-world-app:latest

# View logs
remake app logs hello-world --follow

# Stop
remake app stop hello-world --local
```

## Test without Runtime

```bash
# Run directly with Podman
podman run --rm --name hello-world localhost/hello-world-app:latest

# Stop with Ctrl+C or from another terminal:
podman stop hello-world
```
