FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -m provider
COPY app.py .
RUN mkdir -p /data && chown provider:provider /data
USER provider
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/health',timeout=3)" || exit 1
CMD ["gunicorn","--bind","0.0.0.0:3000","--workers","1","--threads","4","--timeout","45","app:app"]
