FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN python3 -m venv venv
RUN python3 -m pip install --upgrade pip
RUN pip3 install --no-cache-dir -r requirements.txt

COPY api.py process_data.py ./

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8001"]