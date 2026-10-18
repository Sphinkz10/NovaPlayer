FROM golang:1.27.1-bookworm AS age-build
RUN GOBIN=/out go install filippo.io/age/cmd/age@v1.3.2 && GOBIN=/out go install filippo.io/age/cmd/age-keygen@v1.3.2

FROM python:3.13.7-slim
LABEL org.opencontainers.image.source="https://github.com/Sphinkz10/NovaPlayer"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY nova_server ./nova_server
COPY scripts ./scripts
COPY --from=age-build /out/age /out/age-keygen /usr/local/bin/
EXPOSE 8787
USER 10001:10001
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/v1/health/live',timeout=3).read()"
CMD ["python", "-m", "nova_server.launch"]
