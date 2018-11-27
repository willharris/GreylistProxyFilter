# basic container
FROM alpine:edge

RUN apk update \
  && apk add --update-cache --repository http://dl-3.alpinelinux.org/alpine/edge/testing/ --allow-untrusted \
    curl \
    wget \
    postgrey \
    ca-certificates \
  && update-ca-certificates \
  && rm -rf /var/cache/apk/*


# volumes
VOLUME [ "/etc/postgrey" ]

# ports
EXPOSE 10023

# start up
CMD [ "/usr/sbin/postgrey", "--inet", "0.0.0.0:10023", "--max-age", "365", "--delay", "60" ]
