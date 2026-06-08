ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8

# rclone is used by the daily archive (added in a later increment).
RUN apk add --no-cache rclone

WORKDIR /app
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app/ /app/app/
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
