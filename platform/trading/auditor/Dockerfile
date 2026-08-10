FROM python:3.12-slim
WORKDIR /app
COPY trading/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY health.py .
COPY trading/ trading/
WORKDIR /app/trading
ENV PYTHONPATH=/app
EXPOSE 8031
CMD ["uvicorn", "auditor.main:app", "--host", "0.0.0.0", "--port", "8031"]
