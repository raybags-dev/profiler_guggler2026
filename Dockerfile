FROM python:3.13-slim

WORKDIR /app

# System deps for lxml and curl_cffi
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        libxml2-dev \
        libxslt1-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime: sub_profiles/ is created on first write.
# curl sessions must be mounted at runtime, not baked in.
VOLUME ["/app/sub_profiles", "/app/profile_plugins/curl_sessions"]

ENTRYPOINT ["python3"]
CMD ["google_profile_scraper.py"]