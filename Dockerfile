FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim

RUN groupadd -r gridai && useradd -r -g gridai -d /app -s /sbin/nologin gridai

COPY --from=builder /install /usr/local

WORKDIR /app

COPY core/ core/
COPY ai/ ai/
COPY risk/ risk/
COPY data/ data/
COPY backtesting/ backtesting/
COPY dashboard/ dashboard/
COPY config/ config/
COPY scripts/ scripts/
COPY main.py .

RUN mkdir -p state models logs && chown -R gridai:gridai /app

USER gridai

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["python", "main.py", "--mode", "paper"]
