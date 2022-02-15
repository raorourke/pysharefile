import base64
import datetime
import logging
import os
import pickle
import secrets
import time
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from http_requester.creds import UserCreds, Credentials

logging.basicConfig(level=os.environ.get('LOGLEVEL', 'WARNING'))

okta_api_key = os.environ.get('okta_api_key')
client_id = os.environ.get('sharefile_client_id')
client_secret = os.environ.get('sharefile_client_secret')
sf_subdomain = os.environ.get('sf_subdomain')
okta_subdomain = os.environ.get('okta_subdomain')
app_name = 'sharefile'
sf_okta_app_id = os.environ.get('sf_okta_app_id')
okta_base_url = f"https://{okta_subdomain}.okta.com/api/v1"

TOKEN_DIR = Path.home() / '.tokens'

BASE_URL = os.environ.get('sharefile_base_url')
if not BASE_URL:
    raise AttributeError(f"No base url found in environment.")

my_okta = UserCreds(
    'okta_username',
    'okta_password',
    key=lambda x: os.environ.get(x)
)


def millinow():
    return int(round(time.time() * 1000))


def encode_string(plaintext):
    encoded_string = base64.b64encode(plaintext.encode("utf-8"))
    return str(encoded_string, "utf-8")


def printparams(func):
    def wrapped(*args, **kwargs):
        print(f"{args=}")
        print(f"{kwargs=}")
        return func(*args, **kwargs)

    return wrapped


def sf_refresh(self):
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': self._refresh_token,
        'client_id': self._client_id,
        'client_secret': self._client_secret
    }
    r = requests.post(self._token_url, headers=headers, data=data)
    self._token = r.json().get('access_token')
    self._refresh_token = r.json().get('refresh_token')
    self._expiration = datetime.datetime.fromtimestamp(
        millinow() / 1000 + r.json().get('expires_in')
    )


def get_okta_session_token(username: str, password: str, okta_api_key: str, session: requests.Session = None):
    session = session if session is not None else requests.Session()
    okta_url = f"{okta_base_url}/authn"
    headers = {
        'Authorization': f"SSWS {okta_api_key}",
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    data = {
        "username": username,
        "password": password,
        "options": {
            "multiOptionalFactorEnroll": True,
            "warnBeforePasswordExpired": True
        }
    }
    o = session.post(okta_url, headers=headers, json=data)
    token = o.json().get('sessionToken')
    return token, session


def get_sharefile_saml_request(client_id: str, session: requests.Session = None):
    session = session if session is not None else requests.Session()
    redirect_uri = 'https://secure.sharefile.com/oauth/oauthcomplete.aspx'
    state = secrets.token_urlsafe(128)
    url = f"https://{sf_subdomain}.sharefile.com/saml/login"
    params = {
        'response_type': 'code',
        'redirect_uri': redirect_uri,
        'client_id': client_id,
        'state': state,
        'oauth': 1,
        'subdomain': sf_subdomain,
        'appcp': 'sharefile.com',
        'apicp': 'sf-api.com'
    }
    r = session.get(url, params=params)
    soup = BeautifulSoup(r.content.decode('utf8'), 'html.parser')
    return urllib.parse.unquote(soup.find('input', {'id': 'fromURI'}).get('value'))[1:].split('=', 1)[1], session


def get_sharefile_saml_response(token: str, saml_request: str, okta_api_key: str, session: requests.Session = None):
    session = session if session is not None else requests.Session()
    login_url = f"https://{okta_subdomain}.okta.com/login/sessionCookieRedirect"
    redirect_url_base = f"https://{okta_subdomain}.okta.com/app/sharefile/{sf_okta_app_id}/sso/saml"
    redirect_url = f"{redirect_url_base}?SAMLRequest={urllib.parse.quote(saml_request)}"
    headers = {
        'Authorization': f"SSWS {okta_api_key}",
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    params = {
        'checkAccountSetupComplete': True,
        'token': token,
        'redirectUrl': redirect_url
    }
    r = session.get(login_url, headers=headers, params=params)
    soup = BeautifulSoup(r.content.decode('utf8'), 'html.parser')
    return soup.find('input', {'name': 'SAMLResponse'}).get('value'), session


def get_sharefile_auth_code(saml_response: str, session: requests.Session = None):
    session = session if session is not None else requests.Session()
    data = {
        'SAMLResponse': saml_response
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    url = f"https://{sf_subdomain}.sharefile.com/saml/acs"
    t = session.post(url, headers=headers, data=data)
    location = t.history[1].headers.get('location')
    return location.split('?', 1)[1].split('=', 1)[1].split('&', 1)[0], session


def get_sharefile_access_tokens(code: str, client_id: str, client_secret: str, session: requests.Session = None):
    session = session if session is not None else requests.Session()
    oauth_url = f"https://{sf_subdomain}.sf-api.com/oauth/token"
    redirect_uri = 'https://secure.sharefile.com/oauth/oauthcomplete.aspx'
    auth_string = f"{client_id}:{client_secret}"
    headers = {
        'Authorization': f"Basic {encode_string(auth_string)}",
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    data = {
        'grant_type': 'authorization_code',
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'code': code
    }
    y = session.post(oauth_url, headers=headers, data=data)
    access_token = y.json().get('access_token')
    refresh_token = y.json().get('refresh_token')
    expiration = datetime.datetime.fromtimestamp(
        millinow() / 1000 + y.json().get('expires_in')
    )
    return access_token, refresh_token, expiration


def get_sharefile_credentials(
        session: requests.Session = None
) -> Credentials:
    """Shows basic usage of the People API.
    Prints the name of the first 10 connections.
    """
    creds = None
    token_path = TOKEN_DIR / 'sftoken.pickle'
    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh()
        else:
            session = session if session is not None else requests.Session()
            '''
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.105 Safari/537.36'
            })
            '''
            token, session = get_okta_session_token(my_okta.email, my_okta.password, okta_api_key, session)
            saml_request, session = get_sharefile_saml_request(client_id, session)
            saml_response, session = get_sharefile_saml_response(token, saml_request, okta_api_key, session)
            code, session = get_sharefile_auth_code(saml_response, session)
            access_token, refresh_token, expiration = get_sharefile_access_tokens(code, client_id,
                                                                                  client_secret,
                                                                                  session)
            creds = Credentials(
                token=access_token,
                refresh_token=refresh_token,
                expiration=expiration,
                client_id=client_id,
                client_secret=client_secret,
                token_url=BASE_URL,
                format_matrix=(
                    ('Authorization', ('Bearer {}', 'token')),
                ),
                refresh_func=sf_refresh
            )
        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)
    return creds
