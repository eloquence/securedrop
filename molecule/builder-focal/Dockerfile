# ubuntu:focal-20210921
FROM ubuntu@sha256:3555f4996aea6be945ae1532fa377c88f4b3b9e6d93531f47af5d78a7d5e3761


# additional meta-data makes it easier to clean up, find
LABEL org="Freedom of the Press"
LABEL image_name="focal-sd-builder-app"
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get -y update && apt-get upgrade -y && apt-get install -y \
        apache2-dev \
        coreutils \
        debhelper \
        devscripts \
        dh-python \
        dh-systemd \
        gdb \
        git \
        gnupg2 \
        inotify-tools \
        libffi-dev \
        libssl-dev \
        make \
        paxctl \
        python3-all \
        python3-pip \
        python3-setuptools \
        python3-venv \
        rsync \
        ruby \
        sqlite \
        sudo \
        tzdata \
        libevent-dev \
        unzip


# TEMPORARY: install dh-virtualenv from debian unstable, pending focal package:
# https://github.com/spotify/dh-virtualenv/issues/298
RUN echo "deb http://archive.ubuntu.com/ubuntu/ groovy universe" > /etc/apt/sources.list.d/ubuntu-groovy.list
COPY aptpreferences.conf /etc/apt/preferences.d/ubuntu-groovy

RUN apt-get update && apt-get install -y dh-virtualenv

ENV RUST_VERSION 1.52.1

# Install Rust for building cryptography
RUN TMPDIR=`mktemp -d` && cd ${TMPDIR} \
        && curl --proto '=https' --tlsv1.2 -OO -sSf https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init{,.sha256} \
        && mkdir -p target/x86_64-unknown-linux-gnu/release/ \
        && mv rustup-init target/x86_64-unknown-linux-gnu/release/ \
        && sha256sum --check rustup-init.sha256 \
        && cd target/x86_64-unknown-linux-gnu/release/ \
        && chmod +x rustup-init \
        && ./rustup-init --default-toolchain=${RUST_VERSION} -y \
        && cd && rm -rf ${TMPDIR}

RUN echo "source $HOME/.cargo/env" >> $HOME/.bashrc

RUN paxctl -cm /usr/bin/python3.8 && mkdir -p /tmp/build
RUN apt-get clean \
        && rm -rf /var/lib/apt/lists/*
