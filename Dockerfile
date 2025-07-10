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
#RUN sed 's/archive.ubuntu.com/au.archive.ubuntu.com/g' /etc/apt/sources.list > /etc/apt/sourcesau.list && \
#    mv /etc/apt/sourcesau.list /etc/apt/sources.list
RUN --mount=type=cache,target=/var/cache/apt apt-get update
RUN apt install openssl
COPY openssl-legacy.conf /
# RUN ls -al /etc/ssl/
RUN cat /openssl-legacy.conf >> /etc/ssl/openssl.cnf
RUN rm /openssl-legacy.conf

# RUN --mount=type=cache,target=/var/cache/apt apt-get update
RUN apt-get update
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
    wget \
    curl \
    vim  \
    texlive-full
    
RUN apt-get install virtualenv -y
#    rm -rf /var/lib/apt/lists/*
#COPY get-pip.py /tmp/get-pip.py
#RUN python2 /tmp/get-pip.py
RUN apt-get install patch
# RUN ln -s /usr/bin/python2 /usr/bin/python && \
    # pip install --upgrade pip==20.3

# Setup cron
# COPY cron /etc/cron.d/dockercron
COPY startup.sh /
# COPY pre_startup.sh /

# RUN chmod 0644 /etc/cron.d/dockercron && \
#     crontab /etc/cron.d/dockercron && \
#     touch /var/log/cron.log && \
#     mkdir /container-config/ && \
RUN chmod 755 /startup.sh
# RUN chmod +s /startup.sh 
# RUN    chmod 755 /pre_startup.sh && \
# RUN    chmod +s /pre_startup.sh

RUN groupadd -g 5000 oim 
RUN useradd -g 5000 -u 5000 oim -s /bin/bash -d /app 
RUN usermod -a -G sudo oim 
# RUN echo "oim  ALL=(ALL)  NOPASSWD: /startup.sh" > /etc/sudoers.d/oim && \
RUN mkdir /app
RUN chown -R oim.oim /app  

# Default Scripts
RUN wget https://raw.githubusercontent.com/dbca-wa/wagov_utils/main/wagov_utils/bin/default_script_installer.sh -O /tmp/default_script_installer.sh
RUN chmod 755 /tmp/default_script_installer.sh
RUN /tmp/default_script_installer.sh

# Install Python libs from requirements.txt.
FROM builder_base_bfrs as python_libs_bfrs
WORKDIR /app
USER oim
RUN virtualenv -p python2.7 /app/venv
ENV PATH=/app/venv/bin:$PATH
COPY requirements.txt ./
RUN ls -al /app/venv/bin/
RUN whereis pip
RUN pip install -r requirements.txt 
    # Update the Django <1.11 bug in django/contrib/gis/geos/libgeos.py
    # Reference: https://stackoverflow.com/questions/18643998/geodjango-geosexception-error
RUN find /app/venv | grep libgeos
RUN sed -i -e "s/ver = geos_version().decode()/ver = geos_version().decode().split(' ')[0]/" /app/venv/lib/python2.7/site-packages/django/contrib/gis/geos/libgeos.py

# Install the project (ensure that frontend projects have been built prior to this step).
FROM python_libs_bfrs as collect_static_bfrs
COPY gunicorn.ini manage.py ./
COPY bfrs ./bfrs
COPY bfrs_project ./bfrs_project
COPY templates ./templates
COPY python-cron ./
COPY cadastre_table_update ./cadastre_table_update

RUN virtualenv -p python3 /app/venv3
RUN /app/venv3/bin/pip3 install -r /app/cadastre_table_update/requirements.txt

# COPY md4byte_generate.py /bin/md4byte_generate.py
# RUN chmod 755 /bin/md4byte_generate.py 
# COPY compute_hash_patch.diff /tmp/compute_hash_patch.diff
# RUN patch -p1 /usr/local/lib/python2.7/dist-packages/ntlm_auth/compute_hash.py < /tmp/compute_hash_patch.diff
# RUN rm /tmp/compute_hash_patch.diff

# NOTE: we can't currently run the collectstatic step due to how BFRS is written.
# Always be sure to run collectstatic locally prior to building the image.
RUN touch /app/.env && \
    python2 manage.py collectstatic --noinput

FROM collect_static_bfrs as launch_bfrs



# RUN curl -fsSL -o /tmp/install.sh https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh
# RUN chmod 755 /tmp/install.sh
# RUN /tmp/install.sh

# RUN git clone https://github.com/Homebrew/brew ~/.linuxbrew/Homebrew \
# && mkdir ~/.linuxbrew/bin \
# && ln -s ../Homebrew/bin/brew ~/.linuxbrew/bin \
# && eval $(~/.linuxbrew/bin/brew shellenv)
# ENV PATH=/app/.linuxbrew/bin/:$PATH
# RUN ls -al /app/.linuxbrew/bin
# RUN whereis brew
# RUN ln -s ../Homebrew/bin/brew ~/venv/bin/brew
# RUN brew install openssl@1.1
# RUN ls -al /app/.linuxbrew/opt/openssl\@1.1/bin/openssl
# RUN ln -s /app/.linuxbrew/opt/openssl\@1.1/bin/openssl /app/venv/bin/openssl 
# RUN openssl version
EXPOSE 8080
HEALTHCHECK --interval=1m --timeout=5s --start-period=10s --retries=3 CMD ["wget", "-q", "-O", "-", "http://localhost:8080/"]
CMD ["/startup.sh"]
