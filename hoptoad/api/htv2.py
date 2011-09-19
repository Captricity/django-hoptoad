import sys
import socket
import traceback
import logging
import urllib2
from xml.dom.minidom import getDOMImplementation

from django.views.debug import get_safe_settings
from django.core.urlresolvers import resolve
from django.conf import settings

from hoptoad import VERSION, NAME, URL
from hoptoad import get_hoptoad_settings
from hoptoad.api.htv1 import _parse_environment, _parse_request, _parse_session
from hoptoad.api.htv1 import _parse_message


logger = logging.getLogger(__name__)

def _handle_errors(request, response, exception):
    """
    Generates a class/message tuple 
    """
    if response:
        code = "Http%s" % response
        msg = "%(code)s: %(response)s at %(uri)s" % {
                   'code': code,
                   'response': {'Http403': "Forbidden",
                                'Http404': "Page not found"}[code],
                   'uri': request.build_absolute_uri(),
        }
        return (code, msg)

    inst = exception
    if not exception:
        # basically, if we didn't pass in an exception, then
        # try to get the last traceback
        _exc, inst = sys.exc_info()[:2]

    return inst.__class__.__name__, _parse_message(inst)
    
def _request_data(request):
    view_func = resolve(request.path)[0]
    
    return {
        'url'          : request.build_absolute_uri(),
        'component'    : view_func.__module__,
        'action'       : view_func.__name__,
        'params'       : _parse_request(request).items(),
        'session'      : _parse_session(request.session).iteritems() if hasattr(request, 'session') else None,
        'cgi-data'     : _parse_environment(request).iteritems(),
    }

def generate_payload(request, response=None, exception = None, exc_tb = None):
    """Generate an XML payload for a Hoptoad notification.

    Arguments:

    - `request`: The Django request object

    - `response`: Optional. Response code that was received from the webserver

    - `exception`: Optional. Can be a custom exception that implements
                   __str__ and has the class name of the error that is
                   required to be reported.

    """
    exception = exception or sys.exc_info()[1]
    exc_tb    = exc_tb or sys.exc_info()[2]
    
    exc_class, exc_msg = _handle_errors(request, response, exception)
    
    return hoptoad_xml(exc_class, exc_msg, exc_tb, _request_data(request))

def hoptoad_xml(exc_class, exc_msg, exc_tb = None, request_data = None):
    """
    Generates the XML document from the given required and optional 
    
    Request data is a dict of the appropriate items from a request object
    """
    hoptoad_settings = get_hoptoad_settings()

    # api v2 from: http://help.hoptoadapp.com/faqs/api-2/notifier-api-v2
    xdoc = getDOMImplementation().createDocument(None, "notice", None)
    notice = xdoc.firstChild

    # /notice/@version -- should be 2.0
    notice.setAttribute('version', '2.0')

    # /notice/api-key
    api_key = xdoc.createElement('api-key')
    api_key_data = xdoc.createTextNode(hoptoad_settings['HOPTOAD_API_KEY'])
    api_key.appendChild(api_key_data)
    notice.appendChild(api_key)

    # /notice/notifier/name
    # /notice/notifier/version
    # /notice/notifier/url
    notifier = xdoc.createElement('notifier')
    for key, value in zip(["name", "version", "url"], [NAME, VERSION, URL]):
        key = xdoc.createElement(key)
        value = xdoc.createTextNode(str(value))
        key.appendChild(value)
        notifier.appendChild(key)
    notice.appendChild(notifier)

    # /notice/error/class
    # /notice/error/message
    error = xdoc.createElement('error')
    for key, value in zip(["class", "message"], [exc_class, exc_msg]):
        key = xdoc.createElement(key)
        value = xdoc.createTextNode(value)
        key.appendChild(value)
        error.appendChild(key)

    # /notice/error/backtrace/error/line
    backtrace = xdoc.createElement('backtrace')

    # It's possible to not have a traceback on user-defined exceptions
    if exc_tb:
        reversed_backtrace = traceback.extract_tb(exc_tb)
        reversed_backtrace.reverse()

        for filename, lineno, funcname, _text in reversed_backtrace:
            line = xdoc.createElement('line')
            line.setAttribute('file', str(filename))
            line.setAttribute('number', str(lineno))
            line.setAttribute('method', str(funcname))
            backtrace.appendChild(line)
    else:
        line = xdoc.createElement('line')
        line.setAttribute('file', 'unknown')
        line.setAttribute('number', '0')
        line.setAttribute('method', 'unknown')
        backtrace.appendChild(line)
    error.appendChild(backtrace)

    notice.appendChild(error)

    # /notice/request
    if request_data:
        xrequest = xdoc.createElement('request')

        # /notice/request/url -- request.build_absolute_uri()
        xurl = xdoc.createElement('url')
        xurl_data = xdoc.createTextNode(request_data['url'])
        xurl.appendChild(xurl_data)
        xrequest.appendChild(xurl)

        # /notice/request/component -- component where error occured
        comp = xdoc.createElement('component')
        comp_data = xdoc.createTextNode(request_data['component'])
        comp.appendChild(comp_data)
        xrequest.appendChild(comp)

        # /notice/request/action -- action which error occured
        action = xdoc.createElement('action')
        action_data = xdoc.createTextNode(request_data['action'])
        action.appendChild(action_data)
        xrequest.appendChild(action)

        # /notice/request/params/var -- check request.GET/request.POST
        req_params = request_data.get('params', None)
        if req_params:
            params = xdoc.createElement('params')
            for key, value in req_params:
                var = xdoc.createElement('var')
                var.setAttribute('key', key)
                value = xdoc.createTextNode(str(value.encode('ascii', 'replace')))
                var.appendChild(value)
                params.appendChild(var)
            xrequest.appendChild(params)

        # /notice/request/session/var -- check if sessions is enabled..
        if request_data.get("session", None):
            sessions = xdoc.createElement('session')
            for key, value in request_data['session']:
                var = xdoc.createElement('var')
                var.setAttribute('key', key)
                value = xdoc.createTextNode(str(value.encode('ascii', 'replace')))
                var.appendChild(value)
                sessions.appendChild(var)
            xrequest.appendChild(sessions)

        # /notice/request/cgi-data/var -- all meta data
        if request_data.get('cgi-data', None):
            cgidata = xdoc.createElement('cgi-data')
            for key, value in request_data['cgi-data']:
                var = xdoc.createElement('var')
                var.setAttribute('key', key)
                value = xdoc.createTextNode(str(value.encode('ascii', 'replace')))
                var.appendChild(value)
                cgidata.appendChild(var)
            xrequest.appendChild(cgidata)

        notice.appendChild(xrequest)

    # /notice/server-environment
    serverenv = xdoc.createElement('server-environment')

    # /notice/server-environment/project-root -- default to sys.path[0]
    projectroot = xdoc.createElement('project-root')
    projectroot.appendChild(xdoc.createTextNode(sys.path[0]))
    serverenv.appendChild(projectroot)

    # /notice/server-environment/environment-name -- environment name? wtf..
    envname = xdoc.createElement('environment-name')
    envname_text = getattr(settings, 'HOPTOAD_ENV_NAME', socket.gethostname())
    envname_data = xdoc.createTextNode(envname_text)
    envname.appendChild(envname_data)
    serverenv.appendChild(envname)

    appver = xdoc.createElement('app-version')
    appver_text = getattr(settings, 'HOPTOAD_APP_VERSION', '0.0.0')
    appver_data = xdoc.createTextNode(appver_text)
    appver.appendChild(appver_data)
    serverenv.appendChild(appver)

    notice.appendChild(serverenv)
    
    return xdoc.toxml('utf-8')


def _ride_the_toad(payload, timeout, use_ssl):
    """Send a notification (an HTTP POST request) to Hoptoad.

    Parameters:
    payload -- the XML payload for the request from _generate_payload()
    timeout -- the maximum timeout, in seconds, or None to use the default

    """
    headers = {'Content-Type': 'text/xml'}

    url_template = '%s://hoptoadapp.com/notifier_api/v2/notices'
    notification_url = url_template % ("https" if use_ssl else "http")

    # allow the settings to override all urls
    notification_url = get_hoptoad_settings().get('HOPTOAD_NOTIFICATION_URL',
                                                   notification_url)

    r = urllib2.Request(notification_url, payload, headers)
    try:
        if timeout:
            # timeout is 2.6 addition!
            response = urllib2.urlopen(r, timeout=timeout)
        else:
            response = urllib2.urlopen(r)

    except urllib2.URLError:
        logger.exception("Caught an exception while delivering payload "
                         "to hoptoad! Discarding..")
    else:
        try:
            # getcode is 2.6 addition!!
            status = response.getcode()
        except AttributeError:
            # default to just code
            status = response.code

        logger.debug("Returned %s from hoptoad", status)

        if status == 403 and use_ssl:
            if get_hoptoad_settings().get('HOPTOAD_NO_SSL_FALLBACK', False):
                # if we can not use SSL, re-invoke w/o using SSL
                _ride_the_toad(payload, timeout, use_ssl=False)
        if status == 403 and not use_ssl:
            # we were not trying to use SSL but got a 403 anyway
            # something else must be wrong (bad API key?)
            logger.warning("We weren't using any SSL, but received a "
                           "%s anyway! Maybe bad API key?", status)
        if status == 422:
            # couldn't send to hoptoad..
            logger.warning("Couldn't send payload to hoptoad!")
        if status == 500:
            # hoptoad is down
            logger.critical("Hoptoad is down! Can't send payload..discarding.")

def report(payload, timeout):
    use_ssl = get_hoptoad_settings().get('HOPTOAD_USE_SSL', False)
    return _ride_the_toad(payload, timeout, use_ssl)
