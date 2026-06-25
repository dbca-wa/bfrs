# syntax = docker/dockerfile:1.2
# Prepare the base environment.
FROM ghcr.io/dbca-wa/docker-apps-dev:ubuntu_2604_base_python AS builder_base_bfrs

LABEL maintainer="asi@dbca.wa.gov.au"

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Australia/Perth \
    PRODUCTION_EMAIL=True \
    SECRET_KEY="ThisisNotRealKey" \
    USER_SSO="Docker Build" \
    PASS_SSO="ThisIsNotReal" \
    EMAIL_HOST="localhost" \
    FROM_EMAIL="no-reply@dbca.wa.gov.au" \
    SMS_POSTFIX="sms.url.endpoint" \
    VIRTUAL_ENV=/app/venv

    
# Use Australian Mirrors
#RUN sed 's/archive.ubuntu.com/au.archive.ubuntu.com/g' /etc/apt/sources.list > /etc/apt/sourcesau.list && \
#    mv /etc/apt/sourcesau.list /etc/apt/sources.list
# RUN --mount=type=cache,target=/var/cache/apt apt-get update
RUN apt-get update
RUN apt install openssl -y
COPY openssl-legacy.conf /
# RUN ls -al /etc/ssl/
RUN cat /openssl-legacy.conf >> /etc/ssl/openssl.cnf
RUN rm /openssl-legacy.conf

# RUN --mount=type=cache,target=/var/cache/apt apt-get update
RUN apt-get update
RUN apt-get upgrade -y
RUN apt-get install --no-install-recommends -y ipython3

#    texlive-full
RUN apt-get install -y latexmk texlive-lang-english texlive-latex-recommended texlive-base texlive-latex-base texlive-fonts-recommended texlive-latex-extra
RUN apt-get install patch

COPY startup.sh /
RUN chmod 755 /startup.sh

RUN groupadd -g 5000 oim 
RUN useradd -g 5000 -u 5000 oim -s /bin/bash -d /app 
RUN usermod -a -G sudo oim 
# RUN echo "oim  ALL=(ALL)  NOPASSWD: /startup.sh" > /etc/sudoers.d/oim && \
RUN mkdir /app
RUN chown -R oim.oim /app  

# Install Python libs from requirements.txt.
FROM builder_base_bfrs as python_libs_bfrs
WORKDIR /app
USER oim
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH=$VIRTUAL_ENV/bin:$PATH
COPY requirements.txt ./
RUN pip install --upgrade pip
RUN pip install -r requirements.txt 

# Install the project (ensure that frontend projects have been built prior to this step).
FROM python_libs_bfrs as collect_static_bfrs
COPY gunicorn.ini manage.py ./
COPY bfrs ./bfrs
COPY bfrs_project ./bfrs_project
COPY templates ./templates
COPY python-cron ./
COPY bfrs_region_update ./bfrs_region_update
COPY cadastre_table_update ./cadastre_table_update
COPY legislated_tenure_update ./legislated_tenure_update
COPY dept_interest_update ./dept_interest_update
COPY state_forest_update ./state_forest_update
COPY sqlscripts ./sqlscripts

# NOTE: we can't currently run the collectstatic step due to how BFRS is written.
# Always be sure to run collectstatic locally prior to building the image.
RUN touch /app/.env && \
    python manage.py collectstatic --noinput

FROM collect_static_bfrs as launch_bfrs


# Cleanup 
USER root
RUN gem install net-imap -v 0.5.15
RUN gem install erb -v 4.0.3.1
RUN gem install zlib -v 3.1.2
RUN gem install uri -v 0.13.3

RUN wget https://raw.githubusercontent.com/dbca-wa/wagov_utils/refs/heads/main/wagov_utils/bin/package_cleanup_2604.sh -O /tmp/package_cleanup_2604.sh
RUN chmod 755 /tmp/package_cleanup_2604.sh
RUN /tmp/package_cleanup_2604.sh
USER oim

EXPOSE 8080
HEALTHCHECK --interval=1m --timeout=5s --start-period=10s --retries=3 CMD ["wget", "-q", "-O", "-", "http://localhost:8080/"]
CMD ["/startup.sh"]


