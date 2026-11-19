FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV SOLIDCRAFT_CLI=/usr/bin/solidcraft-cli

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates wget \
      libegl1 libgl1 libgcc-s1 \
      libxkbcommon0 libxkbcommon-x11-0 libwayland-client0 \
      libx11-6 libx11-xcb1 libxcb1 libxcursor1 libxi6 \
      libvulkan1 python3-numpy && \
    wget -q -O /tmp/solidcraft.deb \
      https://github.com/tangency-labs/solidcraft/releases/download/v0.44.1/solidcraft-linux-x86_64.deb && \
    echo "6056fec07e771a4abc68f459848dfdb6acc24802bb2043667b770f7b890bd8f6  /tmp/solidcraft.deb" | sha256sum -c - && \
    apt-get install -y --no-install-recommends /tmp/solidcraft.deb && \
    rm -f /tmp/solidcraft.deb && \
    rm -rf /var/lib/apt/lists/* && \
    test -x /usr/bin/solidcraft-cli && \
    mkdir -p /data/inbox /data/previews /data/projects

WORKDIR /data
