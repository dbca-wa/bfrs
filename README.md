# Bushfire Reporting System

This project consists of a redesign and reorganisation of the [Bushfire
Reporting System] corporate application.
corporate application.

# Installation

Create a new virtualenv and install required libraries using `pip`:

    pip install -r requirements.txt

# Environment variables

This project uses confy to set environment
variables (in a `.env` file). Required settings are as follows:

PORT=8080
HOSTNAME=localhost
DJANGO_SETTINGS_MODULE=bfrs_project.settings
CACHE_URL=uwsgi://
DATABASE_URL="postgis://USER:PASSWORD@HOST:PORT/DATABASE_NAME"
SECRET_KEY="ThisIsASecretKey"
DEBUG=True
LDAP_SERVER_URI="ldap://URL"
LDAP_ACCESS_DN="ldap-access-dn"
LDAP_ACCESS_PASSWORD="password"
LDAP_SEARCH_SCOPE="DC=searchscope"

# Running

Use `runserver` to run a local copy of the application:

    python manage.py runserver 0.0.0.0:8080

Run console commands manually:

    python manage.py shell_plus

# Testing (TODO)

Run unit tests for the *bfrs* app as follows:

    python manage.py test bfrs -k -v2

To run tests for e.g. models only:

    python manage.py test bfrs.test_models -k -v2

To obtain coverage reports:

    coverage run --source='.' manage.py test -k -v2
    coverage report -m

Fabric scripts are also available to run tests:

    fab test
    fab test_coverage
