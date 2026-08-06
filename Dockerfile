FROM python:3.12-slim 

# Prevent pip root warnings and bytecode file generation (.pyc)
ENV PIP_ROOT_USER_ACTION=ignore \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# Path inside the linux container 
WORKDIR /app

# System dependencies required for compiling C extensions & MySQL client drivers
RUN apt-get update && apt-get install -y --no-install-recommends \
  default-libmysqlclient-dev \
  build-essential \
  pkg-config \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Upgrade pip and install dependencies cleanly
RUN pip install --no-cache-dir --upgrade pip && \
  pip install --no-cache-dir -r requirements.txt 

# Copy backend codebase to /app
COPY . .

# Expose target port (default container port)
EXPOSE 8080

# Shell-form CMD to allow dynamic $PORT binding across hosting platforms (e.g., Render/GCP)
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"