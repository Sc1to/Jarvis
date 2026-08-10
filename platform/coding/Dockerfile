FROM python:3.12-slim
WORKDIR /app
COPY coding/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY memory/ memory/
COPY tools/ tools/
COPY health.py .
COPY coding/ coding/
WORKDIR /app/coding
ENV PYTHONPATH=/app
EXPOSE 8012
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8012"]
