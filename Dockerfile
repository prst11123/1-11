FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd -r app && useradd -r -g app app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY app ./app
RUN chown -R app:app /app
USER app
EXPOSE 8080
CMD ["sh", "-c", "python -m alembic upgrade head && python -m app.main"]
