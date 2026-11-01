"""Android entry point (python-for-android 'webview' bootstrap).
If the app fails to start, the error is shown on the screen instead of loading forever."""
import html
import traceback

import urllib.parse

try:  # the Flask used on Android is older and needs helpers that newer Werkzeug removed
    import werkzeug.urls as _u
    for _name, _fn in (("url_quote", urllib.parse.quote), ("url_unquote", urllib.parse.unquote),
                       ("url_quote_plus", urllib.parse.quote_plus), ("url_unquote_plus", urllib.parse.unquote_plus)):
        if not hasattr(_u, _name):
            setattr(_u, _name, _fn)
except Exception:
    pass

try:
    from app import app
except Exception:
    err = html.escape(traceback.format_exc())
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Show(BaseHTTPRequestHandler):
        def do_GET(self):
            body = ("<h3>Startup error</h3><pre style='white-space:pre-wrap'>" + err + "</pre>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    HTTPServer(("127.0.0.1", 5000), Show).serve_forever()
else:
    app.run(host="127.0.0.1", port=5000, debug=False)
