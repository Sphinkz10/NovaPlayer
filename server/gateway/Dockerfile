FROM python:3.13.7-slim
LABEL org.opencontainers.image.source="https://github.com/Sphinkz10/NovaPlayer"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends wireguard-tools iproute2 nftables && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-directory.txt ./
RUN pip install --require-hashes -r requirements-directory.txt
COPY nova_server ./nova_server
COPY nova_directory ./nova_directory
USER 0:0
HEALTHCHECK --interval=5s --timeout=3s --start-period=20s --retries=3 CMD ["python", "-m", "nova_server.gateway_container", "--health"]
CMD ["python", "-m", "nova_server.gateway_container"]
