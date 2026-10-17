FROM python:3.13.7-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY nova_server ./nova_server
EXPOSE 8787
USER 10001:10001
CMD ["uvicorn", "nova_server.app:app", "--host", "0.0.0.0", "--port", "8787", "--no-proxy-headers"]
