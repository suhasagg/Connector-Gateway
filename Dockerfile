FROM python:3.12-slim
WORKDIR /app
RUN useradd -r -u 10001 gateway
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY . .
USER gateway
EXPOSE 8080
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8080"]
