ARG BASE=debian:12
FROM ${BASE}
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates python3 sudo curl git xz-utils bash coreutils shellcheck bats tmux \
    && useradd -m -s /bin/bash tester \
    && printf 'tester ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/tester \
    && chmod 0440 /etc/sudoers.d/tester
COPY --chown=tester:tester . /opt/terminal-kit
USER tester
ENV HOME=/home/tester
ENV PATH=/usr/local/bin:/usr/bin:/bin
WORKDIR /opt/terminal-kit
CMD ["bash", "tests/containers/acceptance.sh"]
