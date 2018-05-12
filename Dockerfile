FROM alpine
RUN apk update && apk add py-pip
RUN pip install --upgrade pip
RUN pip install autotrace
ENTRYPOINT autotrace
