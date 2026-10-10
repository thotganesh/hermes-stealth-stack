FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx
COPY router.py /app/router.py
EXPOSE 9378
CMD ["python", "router.py"]
