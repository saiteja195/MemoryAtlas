from .api import create_app
from .logs import configure_logging

configure_logging()
app = create_app()
