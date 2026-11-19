FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY common/ /common/
COPY services/llm/ /app/
ENV PYTHONPATH=/app:/common
EXPOSE 8090
CMD ["uvicorn", "llm.main:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
