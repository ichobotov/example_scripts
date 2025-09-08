FROM python:3.11-slim

WORKDIR .

COPY requirements.txt .
RUN python3 -m venv venv
RUN python3 -m pip install --upgrade pip
RUN pip3 install --no-cache-dir -r requirements.txt

COPY StreamCaster_app.py app_settings.json ./

CMD ["uvicorn", "StreamCaster_app:app", "--host", "0.0.0.0", "--port", "8002"]
