FROM python:3.12-slim
WORKDIR /app
COPY admin/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY memory/ memory/
COPY tools/ tools/
COPY admin/ admin/
WORKDIR /app/admin
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
