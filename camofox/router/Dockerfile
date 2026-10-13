FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir \
    fastapi==0.115.6 \
    "uvicorn[standard]==0.34.0" \
    httpx==0.28.1
COPY router.py /app/router.py
EXPOSE 9378
CMD ["python", "router.py"]
