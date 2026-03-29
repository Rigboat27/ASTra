FROM python:3.10-slim

WORKDIR /app

# Install system-level build tools needed to compile tree-sitter grammars 
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Copy your source code
COPY src/ ./src/

# Install the unified dependencies (A2A backend + Tree-sitter + Async tools)
RUN pip install --no-cache-dir \
    "a2a-sdk[http-server]>=0.3.0" \
    openai>=1.57.0 \
    pydantic>=2.11.4 \
    click>=8.1.8 \
    starlette \
    uvicorn \
    python-dotenv \
    aiohttp>=3.9.0 \
    aiofiles>=23.2.1 \
    tree-sitter>=0.21.0 \
    tree-sitter-languages>=1.10.2 \
    tree-sitter-python>=0.21.0 \
    tree-sitter-cpp>=0.21.0 \
    tree-sitter-java>=0.21.0

# Expose the Nasiko required port
EXPOSE 5000

# Run the A2A server
CMD ["python", "src/__main__.py", "--host", "0.0.0.0", "--port", "5000"]