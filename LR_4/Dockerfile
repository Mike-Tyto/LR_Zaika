FROM python:3.12-slim

RUN useradd -m -u 1000 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY setup_demo.py .

RUN mkdir -p /app/data /app/secrets && chown -R appuser:appuser /app

USER appuser

EXPOSE 9999

ENTRYPOINT ["python", "main.py"]