FROM python:3.9

RUN mkdir /quickshare/
WORKDIR /quickshare/

COPY requirements.txt .
RUN pip install -r requirements.txt && pip install pillow

COPY main.py /quickshare/main.py
COPY templates /quickshare/templates
COPY static /quickshare/static

CMD ["python", "/quickshare/main.py"]
