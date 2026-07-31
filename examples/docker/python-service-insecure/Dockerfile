FROM python:3.12

ARG PIP_INDEX_TOKEN=pypi-AgEIcHlwaS5vcmcCJDY4YTk

RUN apt-get update && apt-get install -y build-essential curl

RUN curl -fsSL https://example.com/install-agent.sh | sh

ADD https://example.com/vendor/lib.tar.gz /opt/lib.tar.gz

COPY . /app
RUN pip install -r /app/requirements.txt

CMD ["python", "/app/main.py"]
