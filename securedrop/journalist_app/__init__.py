# -*- coding: utf-8 -*-

from datetime import datetime, timedelta
from pathlib import Path

from flask import (Flask, session, redirect, url_for, flash, g, request,
                   render_template)
from flask_assets import Environment
from flask_babel import gettext
from flask_wtf.csrf import CSRFProtect, CSRFError
from os import path
from werkzeug.exceptions import default_exceptions

import i18n
import template_filters
import version

from crypto_util import CryptoUtil
from db import db
from journalist_app import account, admin, api, main, col
from journalist_app.utils import (get_source, logged_in,
                                  JournalistInterfaceSessionInterface,
                                  cleanup_expired_revoked_tokens)
from models import InstanceConfig, Journalist
from store import Storage

import typing
# https://www.python.org/dev/peps/pep-0484/#runtime-or-type-checking
if typing.TYPE_CHECKING:
    # flake8 can not understand type annotation yet.
    # That is why all type annotation relative import
    # statements has to be marked as noqa.
    # http://flake8.pycqa.org/en/latest/user/error-codes.html?highlight=f401
    from sdconfig import SDConfig  # noqa: F401
    from typing import Optional, Union, Tuple, Any  # noqa: F401
    from werkzeug import Response  # noqa: F401
    from werkzeug.exceptions import HTTPException  # noqa: F401

_insecure_views = ['main.login', 'static']


def get_logo_url(app: Flask) -> str:
    if not app.static_folder:
        raise FileNotFoundError

    custom_logo_filename = "i/custom_logo.png"
    default_logo_filename = "i/logo.png"
    custom_logo_path = Path(app.static_folder) / custom_logo_filename
    default_logo_path = Path(app.static_folder) / default_logo_filename
    if custom_logo_path.is_file():
        return url_for("static", filename=custom_logo_filename)
    elif default_logo_path.is_file():
        return url_for("static", filename=default_logo_filename)

    raise FileNotFoundError


def create_app(config: 'SDConfig') -> Flask:
    app = Flask(__name__,
                template_folder=config.JOURNALIST_TEMPLATES_DIR,
                static_folder=path.join(config.SECUREDROP_ROOT, 'static'))

    app.config.from_object(config.JOURNALIST_APP_FLASK_CONFIG_CLS)
    app.session_interface = JournalistInterfaceSessionInterface()

    csrf = CSRFProtect(app)
    Environment(app)

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = config.DATABASE_URI
    db.init_app(app)

    # TODO: Attaching a Storage dynamically like this disables all type checking (and
    # breaks code analysis tools) for code that uses current_app.storage; it should be refactored
    app.storage = Storage(config.STORE_DIR,
                          config.TEMP_DIR,
                          config.JOURNALIST_KEY)

    # TODO: Attaching a CryptoUtil dynamically like this disables all type checking (and
    # breaks code analysis tools) for code that uses current_app.storage; it should be refactored
    app.crypto_util = CryptoUtil(
        securedrop_root=config.SECUREDROP_ROOT,
        nouns_file=config.NOUNS,
        adjectives_file=config.ADJECTIVES,
        gpg_key_dir=config.GPG_KEY_DIR,
    )

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e: CSRFError) -> 'Response':
        app.logger.error("The CSRF token is invalid.")
        session.clear()
        msg = gettext('You have been logged out due to inactivity.')
        flash(msg, 'error')
        return redirect(url_for('main.login'))

    def _handle_http_exception(
        error: 'HTTPException'
    ) -> 'Tuple[Union[Response, str], Optional[int]]':
        # Workaround for no blueprint-level 404/5 error handlers, see:
        # https://github.com/pallets/flask/issues/503#issuecomment-71383286
        handler = list(app.error_handler_spec['api'][error.code].values())[0]
        if request.path.startswith('/api/') and handler:
            return handler(error)

        return render_template('error.html', error=error), error.code

    for code in default_exceptions:
        app.errorhandler(code)(_handle_http_exception)

    i18n.configure(config, app)

    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True
    app.jinja_env.globals['version'] = version.__version__
    app.jinja_env.filters['rel_datetime_format'] = \
        template_filters.rel_datetime_format
    app.jinja_env.filters['filesizeformat'] = template_filters.filesizeformat
    app.jinja_env.filters['html_datetime_format'] = \
        template_filters.html_datetime_format

    @app.before_first_request
    def expire_blacklisted_tokens() -> None:
        cleanup_expired_revoked_tokens()

    @app.before_request
    def load_instance_config() -> None:
        app.instance_config = InstanceConfig.get_current()

    @app.before_request
    def setup_g() -> 'Optional[Response]':
        """Store commonly used values in Flask's special g object"""
        if 'expires' in session and datetime.utcnow() >= session['expires']:
            session.clear()
            flash(gettext('You have been logged out due to inactivity.'),
                  'error')

        uid = session.get('uid', None)
        if uid:
            user = Journalist.query.get(uid)
            if user and 'nonce' in session and \
               session['nonce'] != user.session_nonce:
                session.clear()
                flash(gettext('You have been logged out due to password change'),
                      'error')

        session['expires'] = datetime.utcnow() + \
            timedelta(minutes=getattr(config,
                                      'SESSION_EXPIRATION_MINUTES',
                                      120))

        uid = session.get('uid', None)
        if uid:
            g.user = Journalist.query.get(uid)

        i18n.set_locale(config)

        if app.instance_config.organization_name:
            g.organization_name = app.instance_config.organization_name
        else:
            g.organization_name = gettext('SecureDrop')

        try:
            g.logo = get_logo_url(app)
        except FileNotFoundError:
            app.logger.error("Site logo not found.")

        if request.path.split('/')[1] == 'api':
            pass  # We use the @token_required decorator for the API endpoints
        else:  # We are not using the API
            if request.endpoint not in _insecure_views and not logged_in():
                return redirect(url_for('main.login'))

        if request.method == 'POST':
            filesystem_id = request.form.get('filesystem_id')
            if filesystem_id:
                g.filesystem_id = filesystem_id
                g.source = get_source(filesystem_id)

        return None

    app.register_blueprint(main.make_blueprint(config))
    app.register_blueprint(account.make_blueprint(config),
                           url_prefix='/account')
    app.register_blueprint(admin.make_blueprint(config), url_prefix='/admin')
    app.register_blueprint(col.make_blueprint(config), url_prefix='/col')
    api_blueprint = api.make_blueprint(config)
    app.register_blueprint(api_blueprint, url_prefix='/api/v1')
    csrf.exempt(api_blueprint)

    return app
