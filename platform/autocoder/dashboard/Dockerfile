FROM python:3.12-slim
WORKDIR /app
COPY autocoder/dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY memory/ memory/
COPY autocoder/dashboard/ autocoder/dashboard/
WORKDIR /app/autocoder/dashboard
ENV PYTHONPATH=/app
EXPOSE 8050
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8050"]
