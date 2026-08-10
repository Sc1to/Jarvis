FROM python:3.12-slim
WORKDIR /app
COPY autocoder/re-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY memory/ memory/
COPY autocoder/re-agent/ autocoder/re-agent/
WORKDIR /app/autocoder/re-agent
ENV PYTHONPATH=/app
EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
