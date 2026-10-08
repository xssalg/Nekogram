#!/usr/bin/env python3
"""Exercise the production CONNECT transport against local TCP proxy fixtures."""
import base64
import concurrent.futures
import pathlib
import socket
import subprocess
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'TMessagesProj/src/main/java/org/telegram/utils/proxy/HttpProxyTransport.java'


def recv_exact(sock, n):
    data = b''
    while len(data) < n:
        part = sock.recv(n - len(data))
        if not part:
            raise EOFError(data)
        data += part
    return data


def run_case(classes, name, response=b'HTTP/1.1 200 Connection established\r\n\r\n',
             credentials=False, family=1, rejected=False, local_auth=True, fragment=False):
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen()
    server.settimeout(10)
    seen = []
    errors = []

    def upstream():
        try:
            with server.accept()[0] as sock:
                sock.settimeout(10)
                request = b''
                while not request.endswith(b'\r\n\r\n'):
                    request += recv_exact(sock, 1)
                seen.append(request)
                authority = b'[2001:db8:0:0:0:0:0:1]:443' if family == 4 else b'149.154.167.50:443'
                if family == 3:
                    authority = b'dc.example:443'
                assert request.startswith(b'CONNECT ' + authority + b' HTTP/1.1\r\n')
                expected = b'Proxy-Authorization: Basic ' + base64.b64encode('alice:p:a ss'.encode())
                assert (expected in request) == credentials
                if fragment:
                    for byte in response:
                        sock.sendall(bytes([byte]))
                else:
                    sock.sendall(response + (b'GREETING' if not rejected else b''))
                if not rejected:
                    data = recv_exact(sock, 65536)
                    assert data == bytes(range(256)) * 256
                    sock.sendall(data)
                    assert sock.recv(1) == b''
        except BaseException as exc:
            errors.append(exc)
        finally:
            server.close()

    thread = None
    if local_auth:
        thread = threading.Thread(target=upstream, daemon=True)
        thread.start()
    process = subprocess.Popen(['java', '-cp', str(classes), 'BridgeMain', str(server.getsockname()[1]),
                                'alice' if credentials else '', 'p:a ss' if credentials else ''],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        port, user, token = process.stdout.readline().strip().split(' ')
        with socket.create_connection(('127.0.0.1', int(port)), timeout=10) as client:
            client.sendall(b'\x05\x02\x00\x02')
            assert recv_exact(client, 2) == b'\x05\x02'
            password = token.encode() if local_auth else b'wrong'
            client.sendall(b'\x01' + bytes([len(user)]) + user.encode() + bytes([len(password)]) + password)
            assert recv_exact(client, 2) == (b'\x01\x00' if local_auth else b'\x01\x01')
            if local_auth:
                dest = socket.inet_pton(socket.AF_INET6, '2001:db8::1') if family == 4 else socket.inet_aton('149.154.167.50')
                if family == 3:
                    dest = b'\x0adc.example'
                client.sendall(b'\x05\x01\x00' + bytes([family]) + dest + b'\x01\xbb')
                if rejected:
                    try:
                        reply = recv_exact(client, 10)
                        assert reply[1] != 0, reply
                    except (EOFError, ConnectionResetError):
                        pass
                else:
                    assert recv_exact(client, 10)[1] == 0
                    if not fragment:
                        assert recv_exact(client, 8) == b'GREETING'
                    payload = bytes(range(256)) * 256
                    client.sendall(payload)
                    client.shutdown(socket.SHUT_WR)
                    assert recv_exact(client, len(payload)) == payload
                    assert client.recv(1) == b''
                thread.join(12)
                assert not thread.is_alive(), 'Upstream did not close'
                assert not errors, errors
            else:
                assert client.recv(1) == b''
                assert not seen
    finally:
        process.communicate('\n', timeout=10)
        assert process.returncode == 0
        server.close()
    print('PASS', name)


with tempfile.TemporaryDirectory() as tmp:
    classes = pathlib.Path(tmp)
    (classes / 'BridgeMain.java').write_text('''
import org.telegram.utils.proxy.HttpProxyTransport;
public class BridgeMain {
  public static void main(String[] args) throws Exception {
    try (HttpProxyTransport t = new HttpProxyTransport("127.0.0.1", Integer.parseInt(args[0]), args[1], args[2])) {
      System.out.println(t.getPort() + " " + t.getUser() + " " + t.getPassword());
      System.out.flush();
      System.in.read();
    }
  }
}
''')
    subprocess.run(['javac', '-d', str(classes), str(SOURCE), str(classes / 'BridgeMain.java')], check=True)
    cases = [
        ('IPv4 CONNECT, coalesced payload and half-close', {}),
        ('Basic proxy authentication', {'credentials': True}),
        ('IPv6 CONNECT authority', {'family': 4}),
        ('Hostname CONNECT authority', {'family': 3}),
        ('Fragmented HTTP response', {'fragment': True}),
        ('Interim HTTP response', {'response': b'HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 200 OK\r\n\r\n'}),
        ('407 fails closed', {'response': b'HTTP/1.1 407 Proxy Authentication Required\r\n\r\n', 'rejected': True}),
        ('Malformed response fails closed', {'response': b'NOTHTTP 200 OK\r\n\r\n', 'rejected': True}),
        ('Oversized headers fail closed', {'response': b'HTTP/1.1 200 OK\r\nX: ' + b'a' * 32768 + b'\r\n\r\n', 'rejected': True}),
        ('Loopback rejects unauthenticated users', {'local_auth': False}),
    ]
    for name, kwargs in cases:
        run_case(classes, name, **kwargs)
