from fastapi.responses import Response
from app.routes import _set_security_headers


def test_blob_images_allowed_without_allowing_blob_scripts():
    response = Response()
    _set_security_headers(response)
    directives = dict(part.strip().split(' ', 1) for part in
                      response.headers['Content-Security-Policy'].split(';') if part.strip())
    assert 'blob:' in directives['img-src'].split()
    assert 'blob:' not in directives['script-src'].split()
    assert directives['object-src'] == "'none'"
