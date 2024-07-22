# syntax = docker/dockerfile:1.2

# Prepare the base environment.
FROM ubuntu:22.04 as builder_base_bfrs

LABEL maintainer="asi@dbca.wa.gov.au"

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Australia/Perth \
    PRODUCTION_EMAIL=True \
    SECRET_KEY="ThisisNotRealKey" \
    USER_SSO="Docker Build" \
    PASS_SSO="ThisIsNotReal" \
    EMAIL_HOST="localhost" \
    FROM_EMAIL="no-reply@dbca.wa.gov.au" \
    SMS_POSTFIX="sms.url.endpoint"

# Use Australian Mirrors
RUN sed 's/archive.ubuntu.com/au.archive.ubuntu.com/g' /etc/apt/sources.list > /etc/apt/sourcesau.list && \
    mv /etc/apt/sourcesau.list /etc/apt/sources.list
RUN --mount=type=cache,target=/var/cache/apt apt-get update
RUN apt install openssl
COPY openssl-legacy.conf /
RUN ls -al /etc/ssl/
RUN cat /openssl-legacy.conf >> /etc/ssl/openssl.cnf
RUN rm /openssl-legacy.conf

RUN apt-get upgrade -y && \
    apt-get install --no-install-recommends -y \
    binutils \
    cron \
    gcc \
    gdal-bin \
    git \
    libmagic-dev \
    libproj-dev \
    libpq-dev \
    python2 \
    python2-dev \
    python-pip \
    python-setuptools \
    ipython3 \
    tzdata \
    wget && \
    rm -rf /var/lib/apt/lists/*

RUN ln -s /usr/bin/python2 /usr/bin/python && \
    pip2 install --upgrade pip==20.3

# Setup cron
COPY cron /etc/cron.d/dockercron
COPY startup.sh pre_startup.sh /

RUN chmod 0644 /etc/cron.d/dockercron && \
    crontab /etc/cron.d/dockercron && \
    touch /var/log/cron.log && \
    mkdir /container-config/ && \
    chmod 755 /startup.sh && \
    chmod +s /startup.sh && \
    chmod 755 /pre_startup.sh && \
    chmod +s /pre_startup.sh

# Install Python libs from requirements.txt.
FROM builder_base_bfrs as python_libs_bfrs
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt && \
    # Update the Django <1.11 bug in django/contrib/gis/geos/libgeos.py
    # Reference: https://stackoverflow.com/questions/18643998/geodjango-geosexception-error
    sed -i -e "s/ver = geos_version().decode()/ver = geos_version().decode().split(' ')[0]/" /usr/local/lib/python2.7/dist-packages/django/contrib/gis/geos/libgeos.py

# Install the project (ensure that frontend projects have been built prior to this step).
FROM python_libs_bfrs as collect_static_bfrs
COPY gunicorn.ini manage.py ./
COPY bfrs ./bfrs
COPY bfrs_project ./bfrs_project
COPY templates ./templates

# NOTE: we can't currently run the collectstatic step due to how BFRS is written.
# Always be sure to run collectstatic locally prior to building the image.
RUN touch /app/.env && \
    python2 manage.py collectstatic --noinput

FROM collect_static_bfrs as launch_bfrs

# kubernetes health checks script
RUN wget https://raw.githubusercontent.com/dbca-wa/wagov_utils/main/wagov_utils/bin/health_check.sh -O /bin/health_check.sh
RUN chmod 755 /bin/health_check.sh

EXPOSE 8080
HEALTHCHECK --interval=1m --timeout=5s --start-period=10s --retries=3 CMD ["wget", "-q", "-O", "-", "http://localhost:8080/"]
CMD ["/pre_startup.sh"]
