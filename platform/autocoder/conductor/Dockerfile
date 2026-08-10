FROM python:3.12-slim
WORKDIR /app
COPY autocoder/conductor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY memory/ memory/
COPY tools/ tools/
COPY health.py .
COPY autocoder/conductor/ autocoder/conductor/
WORKDIR /app/autocoder/conductor
ENV PYTHONPATH=/app
EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
