FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY common/ /common/
COPY services/relay/ /app/
ENV PYTHONPATH=/app:/common
EXPOSE 8081
CMD ["uvicorn", "relay.main:app", "--host", "0.0.0.0", "--port", "8081", "--no-access-log"]
