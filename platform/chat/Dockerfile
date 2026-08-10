FROM python:3.12-slim
WORKDIR /app
COPY chat/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY health.py .
COPY chat/ chat/
WORKDIR /app/chat
ENV PYTHONPATH=/app
EXPOSE 8010
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
