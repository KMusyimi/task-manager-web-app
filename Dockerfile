FROM python:3.12-slim 

# path inside the linux container 
WORKDIR /app

# These system dependencies are required for the MySQL drivers in your requirements.txt
RUN apt-get update && apt-get install -y \
  default-libmysqlclient-dev \
  build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt 

# Copy from root to '/app'
COPY . .

# CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]