from django.conf import settings
from itertools import ifilter

__version__ = 0.3
VERSION = __version__
NAME = "django-hoptoad"
URL = "http://sjl.bitbucket.org/django-hoptoad/"


def get_hoptoad_settings():
    hoptoad_settings = getattr(settings, 'HOPTOAD_SETTINGS', {})
    
    if not hoptoad_settings:
        # do some backward compatibility work to combine all hoptoad
        # settings in a dictionary
        
        # for every attribute that starts with hoptoad
        for attr in ifilter(lambda x: x.startswith('HOPTOAD'), dir(settings)):
            hoptoad_settings[attr] = getattr(settings, attr)
        
    return hoptoad_settings

def report_error(exception, traceback = None, timeout = get_hoptoad_settings().get('HOPTOAD_TIMEOUT', None), request_data = None):
    """
    Report an exception that is not part of a request/response flow
    
    The request_data object may be a dict with keys for relevant values in the 
    Airbrake XML API. 
    """
    
    from hoptoad.handlers import get_handler
    from hoptoad.api import htv2
    
    payload = htv2.hoptoad_xml(exception.__class__.__name__, unicode(exception), traceback, request_data)
    get_handler().enqueue(payload, timeout)
