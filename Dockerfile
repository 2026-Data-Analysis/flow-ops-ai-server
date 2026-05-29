FROM python:3.12

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]