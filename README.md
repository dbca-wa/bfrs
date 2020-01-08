# Bushfire Reporting System

This project consists of a redesign and reorganisation of the [Bushfire
Reporting System] corporate application.
corporate application.

# Installation

Create a new virtualenv and install required libraries using `pip`:

    pip install -r requirements.txt

# Environment variables

This project uses confy to set environment
variables (in a `.env` file). Minimum required settings are as follows:

    DATABASE_URL="postgis://username:password@hostname/database"
    SECRET_KEY="SecretKey"
    USER_SSO="email@dbca.wa.gov.au"
    PASS_SSO="password"
    EMAIL_HOST="smtp.hostname"
    FROM_EMAIL="email@dbca.wa.gov.au"
    SMS_POSTFIX="sms.url.endpoint"

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
