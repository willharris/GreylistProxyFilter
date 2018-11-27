# basic container
FROM ubuntu:16.04

RUN apt-get update && \
    apt-get install --yes --no-install-recommends \
    build-essential \
    net-tools \
    postgrey \
    python3 \
    python3-pip \
    python3-setuptools \
    telnet \
    zsh

RUN mkdir -p /srv

COPY ./ /srv

WORKDIR /srv

RUN pip3 install -r requirements/development.txt

# start up
CMD while true; do sleep 1; done
