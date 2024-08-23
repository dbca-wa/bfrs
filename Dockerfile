# Dockerfile to build BFRS application images.
# Prepare the base environment.
FROM ubuntu:24.04 as builder_base_bfrs
MAINTAINER asi@dbca.wa.gov.au
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Australia/Perth
ENV PRODUCTION_EMAIL=True
ENV SECRET_KEY="ThisisNotRealKey"
ENV USER_SSO="Docker Build"
ENV PASS_SSO="ThisIsNotReal"
ENV EMAIL_HOST="localhost"
ENV FROM_EMAIL="no-reply@dbca.wa.gov.au"
ENV SMS_POSTFIX="sms.url.endpoint"

RUN apt-get update -y
RUN apt-get install --no-install-recommends -y wget git libmagic-dev gcc binutils libproj-dev gdal-bin
RUN apt-get install --no-install-recommends -y python3 python3-setuptools python3-dev python3-pip tzdata virtualenv
RUN apt-get install --no-install-recommends -y gcc bzip2 build-essential libpq-dev

# RUN pip install --upgrade pip

RUN groupadd -g 5000 oim 
RUN useradd -g 5000 -u 5000 oim -s /bin/bash -d /app
RUN mkdir /app 
RUN chown -R oim.oim /app 

ENV TZ=Australia/Perth

# Install Python libs from requirements.txt.
FROM builder_base_bfrs as python_libs_bfrs
WORKDIR /app
USER oim
RUN virtualenv -p python3 /app/venv
ENV PATH=/app/venv/bin:$PATH
RUN ls -la /app/venv/bin
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
  # Update the Django <1.11 bug in django/contrib/gis/geos/libgeos.py
  # Reference: https://stackoverflow.com/questions/18643998/geodjango-geosexception-error
  # && sed -i -e "s/ver = geos_version().decode()/ver = geos_version().decode().split(' ')[0]/" /usr/local/lib/python2.7/dist-packages/django/contrib/gis/geos/libgeos.py \
RUN rm -rf /var/lib/{apt,dpkg,cache,log}/ /tmp/* /var/tmp/*

# Install the project (ensure that frontend projects have been built prior to this step).
FROM python_libs_bfrs
COPY gunicorn.ini manage.py ./
COPY bfrs_api_wrapper ./bfrs_api_wrapper
# NOTE: we can't currently run the collectstatic step due to how BFRS is written.
# Always be sure to run collectstatic locally prior to building the image.
RUN touch /app/.env
COPY .git ./.git
# RUN python manage.py collectstatic --noinput

EXPOSE 8080
HEALTHCHECK --interval=1m --timeout=5s --start-period=10s --retries=3 CMD ["wget", "-q", "-O", "-", "http://localhost:8080/"]
CMD ["gunicorn", "bfrs_api_wrapper.wsgi", "--bind", ":8080", "--config", "gunicorn.ini"]
