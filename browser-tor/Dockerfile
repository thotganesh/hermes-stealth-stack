FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app
RUN apt-get update && apt-get install -y libxml2-dev libxslt1-dev python3-dev && rm -rf /var/lib/apt/lists/*
RUN pip install fastapi uvicorn httpx playwright==1.48.0 stem readability-lxml html2text lxml
COPY app.py /app/app.py

EXPOSE 8081
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8081"]
