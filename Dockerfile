FROM python:3.11-slim

# Prevent Python from buffering stdout/stderr and silence interactive debconf prompts
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

# Install system build dependencies (noninteractive mode prevents debconf warnings)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install and upgrade pip without root warnings, then install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code and knowledge base
COPY . .

# Cloud Run injects $PORT (defaults to 8080)
ENV PORT=8080
EXPOSE 8080

CMD ["python", "app.py"]
