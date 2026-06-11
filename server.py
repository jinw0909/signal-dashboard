from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_BASE_URL = "http://3.36.217.232"


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/"):
            self.proxy_api_request()
            return

        super().do_GET()

    def proxy_api_request(self):
        target_url = API_BASE_URL + self.path[len("/api"):]

        try:
            request = Request(
                target_url,
                method="GET",
                headers={
                    "Accept": "application/json"
                }
            )

            with urlopen(request, timeout=10) as response:
                body = response.read()

                self.send_response(response.status)
                self.send_header(
                    "Content-Type",
                    response.headers.get(
                        "Content-Type",
                        "application/json"
                    )
                )
                self.send_header(
                    "Content-Length",
                    str(len(body))
                )
                self.end_headers()
                self.wfile.write(body)

        except HTTPError as error:
            body = error.read()

            self.send_response(error.code)
            self.send_header(
                "Content-Type",
                error.headers.get(
                    "Content-Type",
                    "application/json"
                )
            )
            self.send_header(
                "Content-Length",
                str(len(body))
            )
            self.end_headers()
            self.wfile.write(body)

        except URLError as error:
            message = (
                f'{{"message":"API 연결 실패: {error.reason}"}}'
            ).encode("utf-8")

            self.send_response(502)
            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8"
            )
            self.send_header(
                "Content-Length",
                str(len(message))
            )
            self.end_headers()
            self.wfile.write(message)


if __name__ == "__main__":
    host = "127.0.0.1"
    port = 5500

    server = ThreadingHTTPServer(
        (host, port),
        Handler
    )

    print(f"Open http://{host}:{port}")
    server.serve_forever()