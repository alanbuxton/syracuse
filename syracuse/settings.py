"""
Django settings for syracuse project.

Generated by 'django-admin startproject' using Django 4.2.4.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.2/ref/settings/
"""

from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("SECRET_KEY",'django-insecure-=vq-#5ghwtp7_()k7xi$goljno#*4^)-yaim=q*ql%7nl^r*5#')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DJANGO_DEBUG",'True').lower() == 'true'
# Only for end users; auth is always needed for
REQUIRE_END_USER_LOGIN = os.environ.get("SYRACUSE_REQUIRE_END_USER_LOGIN","true").lower() != "false"
MOTD = os.environ.get("SYRACUSE_MOTD","<h4>Welcome to Syracuse, your database of key events in company lifecycles, updated daily.</h4>")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS","localhost,127.0.0.1").split(",")


# Application definition

INSTALLED_APPS = [
    'django_neomodel',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.discord',
    'allauth.socialaccount.providers.facebook',
    'allauth.socialaccount.providers.github',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.instagram',
    'allauth.socialaccount.providers.linkedin',
    'allauth.socialaccount.providers.snapchat',
    'topics.apps.TopicsConfig',
    'feedbacks.apps.FeedbacksConfig',
    'trackeditems.apps.TrackeditemsConfig',
    'integration.apps.IntegrationConfig',
    'rest_framework',
    'django_bootstrap5',
    'rest_framework.authtoken',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = 'syracuse.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR,"templates"), ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.request',
            ],
        },
    },
]

AUTHENTICATION_BACKENDS = [
    # Needed to login by username in Django admin, regardless of `allauth`
    'django.contrib.auth.backends.ModelBackend',
    # `allauth` specific authentication methods, such as login by email
    'allauth.account.auth_backends.AuthenticationBackend',
]

WSGI_APPLICATION = 'syracuse.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': "django.db.backends.postgresql",
        "HOST": os.environ.get("POSTGRES_HOST","localhost"),
        "NAME": os.environ.get("POSTGRES_NAME","syracuse_pg_db"),
        "USER": os.environ.get("POSTGRES_USER","syracuse_user"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD","itsasecret"),
        "PORT": os.environ.get("POSTGRES_PORT",5432),
    }
}

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'INFO',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG',
    },
    'loggers': {
        'syracuse': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Neomodel

NEOMODEL_NEO4J_SCHEME = os.environ.get('NEO4J_SCHEME','bolt')
NEOMODEL_NEO4J_USERNAME = os.environ.get('NEO4J_USERNAME','neo4j')
NEOMODEL_NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD','itsasecret')
NEOMODEL_NEO4J_HOSTNAME = os.environ.get('NEO4J_HOSTNAME','localhost')
NEOMODEL_NEO4J_PORT = os.environ.get('NEO4J_PORT',7687)
NEOMODEL_NEO4J_BOLT_URL = f'{NEOMODEL_NEO4J_SCHEME}://{NEOMODEL_NEO4J_USERNAME}:{NEOMODEL_NEO4J_PASSWORD}@{NEOMODEL_NEO4J_HOSTNAME}:{NEOMODEL_NEO4J_PORT}'

# all-auth
SITE_ID = 1
ACCOUNT_EMAIL_VERIFICATION = "none"
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_ON_GET = True

BREVO_API_KEY = os.environ['BREVO_API_KEY']
