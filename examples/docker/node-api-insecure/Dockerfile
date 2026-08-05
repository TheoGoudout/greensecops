# A Node service built the way a first Dockerfile usually looks: one stage, the
# whole source tree copied before the install, a registry token copied in to
# reach a private package, and TLS verification turned off to get past a
# corporate proxy. Every line of it is something that appears in real
# repositories, which is the point of the fixture.
FROM node:22

# Reaching a private registry by copying the developer's own .npmrc. The layer
# keeps the token whether or not a later instruction deletes the file.
COPY .npmrc /root/.npmrc

RUN apt-get update
RUN apt-get install -y curl git python3

RUN npm config set strict-ssl false

COPY . /app

RUN cd /app && npm install

RUN chmod -R 777 /app

EXPOSE 3000

CMD node /app/server.js
