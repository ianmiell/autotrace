FROM alpine
RUN apk update && apk add py-pip gcc python-dev libc-dev
RUN pip install --upgrade pip
RUN pip install autotrace
ENTRYPOINT autotrace
