FROM python:3.12-slim 

ENV PIP_ROOT_USER_ACTION=ignore \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

WORKDIR /app

# Install compilation headers needed for C extensions & MySQL
RUN apt-get update && apt-get install -y --no-install-recommends \
  default-libmysqlclient-dev \
  build-essential \
  pkg-config \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Upgraded pip and verbose installation
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"