package org.telegram.utils.proxy;

import java.io.Closeable;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.Semaphore;

/** Authenticated loopback SOCKS endpoint carrying MTProto over HTTP CONNECT. */
public final class HttpProxyTransport implements Closeable {
    private static HttpProxyTransport active;
    private final String host, user, password;
    private final int port;
    private final String token = UUID.randomUUID().toString();
    private final ServerSocket listener;
    private final Set<Socket> sockets = ConcurrentHashMap.newKeySet();
    private final Semaphore slots = new Semaphore(64);
    private final ExecutorService workers = Executors.newCachedThreadPool(r -> {
        Thread thread = new Thread(r, "HTTP proxy");
        thread.setDaemon(true);
        return thread;
    });
    private volatile boolean closed;

    public static synchronized HttpProxyTransport start(String host, int port, String user, String password) throws IOException {
        if (active != null && !active.closed && active.host.equals(host) && active.port == port
                && active.user.equals(user) && active.password.equals(password)) {
            return active;
        }
        stop();
        active = new HttpProxyTransport(host, port, user, password);
        return active;
    }

    public static synchronized void stop() {
        if (active != null) {
            active.close();
            active = null;
        }
    }

    public HttpProxyTransport(String host, int port, String user, String password) throws IOException {
        if (host.isEmpty() || port < 1 || port > 65535 || user.indexOf(':') >= 0) {
            throw new IOException("Invalid HTTP proxy settings");
        }
        this.host = host;
        this.port = port;
        this.user = user;
        this.password = password;
        listener = new ServerSocket(0, 64, InetAddress.getByName("127.0.0.1"));
        workers.execute(this::accept);
    }

    public int getPort() { return listener.getLocalPort(); }
    public String getUser() { return "http"; }
    public String getPassword() { return token; }

    private void accept() {
        while (!closed) {
            try {
                Socket socket = listener.accept();
                if (!slots.tryAcquire()) {
                    socket.close();
                    continue;
                }
                synchronized (sockets) {
                    if (closed) {
                        socket.close();
                        slots.release();
                        break;
                    }
                    sockets.add(socket);
                    workers.execute(() -> serve(socket));
                }
            } catch (IOException e) {
                close();
            }
        }
    }

    private void serve(Socket client) {
        Socket upstream = new Socket(Proxy.NO_PROXY);
        try (client; upstream) {
            synchronized (sockets) {
                if (closed) return;
                sockets.add(upstream);
            }
            client.setSoTimeout(15000);
            InputStream in = client.getInputStream();
            OutputStream out = client.getOutputStream();
            if (read(in) != 5) throw new IOException("Expected SOCKS5");
            byte[] methods = readBytes(in, read(in));
            boolean auth = false;
            for (byte method : methods) auth |= method == 2;
            out.write(new byte[]{5, (byte) (auth ? 2 : 255)});
            if (!auth) return;
            if (read(in) != 1) throw new IOException("Expected username authentication");
            String localUser = new String(readBytes(in, read(in)), StandardCharsets.UTF_8);
            String localPassword = new String(readBytes(in, read(in)), StandardCharsets.UTF_8);
            boolean authorized = getUser().equals(localUser) && token.equals(localPassword);
            out.write(new byte[]{1, (byte) (authorized ? 0 : 1)});
            if (!authorized) return;
            if (read(in) != 5 || read(in) != 1 || read(in) != 0) {
                throw new IOException("Only SOCKS CONNECT is supported");
            }
            int type = read(in);
            String destination;
            if (type == 1 || type == 4) {
                destination = InetAddress.getByAddress(readBytes(in, type == 1 ? 4 : 16)).getHostAddress();
                if (type == 4) destination = "[" + destination + "]";
            } else if (type == 3) {
                destination = new String(readBytes(in, read(in)), StandardCharsets.US_ASCII);
                if (!destination.matches("[A-Za-z0-9._-]+")) throw new IOException("Invalid destination");
            } else {
                throw new IOException("Unsupported address family");
            }
            int destinationPort = (read(in) << 8) | read(in);
            if (destinationPort == 0) throw new IOException("Invalid destination port");
            upstream.connect(new InetSocketAddress(host, port), 15000);
            upstream.setSoTimeout(15000);
            String authority = destination + ":" + destinationPort;
            String request = "CONNECT " + authority + " HTTP/1.1\r\nHost: " + authority + "\r\n";
            if (!user.isEmpty() || !password.isEmpty()) {
                request += "Proxy-Authorization: Basic " + Base64.getEncoder().encodeToString(
                        (user + ":" + password).getBytes(StandardCharsets.UTF_8)) + "\r\n";
            }
            upstream.getOutputStream().write((request + "\r\n").getBytes(StandardCharsets.US_ASCII));
            InputStream response = upstream.getInputStream();
            boolean connected = false;
            for (int interim = 0; interim < 5; interim++) {
                String headers = readHeaders(response);
                String status = headers.substring(0, headers.indexOf("\r\n"));
                if (!status.matches("HTTP/1\\.[01] [0-9]{3}( .*)?")) throw new IOException("Invalid HTTP response");
                int code = Integer.parseInt(status.substring(9, 12));
                if (code >= 200 && code < 300) {
                    connected = true;
                    break;
                }
                if (code < 100 || code >= 200 || code == 101) break;
            }
            if (!connected) {
                out.write(new byte[]{5, 5, 0, 1, 0, 0, 0, 0, 0, 0});
                return;
            }
            out.write(new byte[]{5, 0, 0, 1, 0, 0, 0, 0, 0, 0});
            client.setSoTimeout(0);
            upstream.setSoTimeout(0);
            Future<?> downstream = workers.submit(() -> {
                try {
                    relay(upstream, client);
                } catch (IOException e) {
                    closeSocket(client);
                    closeSocket(upstream);
                }
            });
            relay(client, upstream);
            downstream.get();
        } catch (Exception ignored) {
            // Closing the loopback connection makes tgnet retry through this proxy.
            // Never fall back to a direct connection after a proxy failure.
        } finally {
            sockets.remove(client);
            sockets.remove(upstream);
            slots.release();
        }
    }

    private static int read(InputStream in) throws IOException {
        int value = in.read();
        if (value < 0) throw new EOFException();
        return value;
    }

    private static byte[] readBytes(InputStream in, int length) throws IOException {
        byte[] bytes = new byte[length];
        int offset = 0;
        while (offset < length) {
            int count = in.read(bytes, offset, length - offset);
            if (count < 0) throw new EOFException();
            offset += count;
        }
        return bytes;
    }

    private static String readHeaders(InputStream in) throws IOException {
        StringBuilder headers = new StringBuilder();
        int tail = 0;
        while (headers.length() < 32768) {
            int b = read(in);
            headers.append((char) b);
            tail = (tail << 8) | b;
            if (tail == 0x0d0a0d0a) return headers.toString();
        }
        throw new IOException("HTTP proxy response headers too large");
    }

    private static void relay(Socket from, Socket to) throws IOException {
        byte[] buffer = new byte[32768];
        InputStream in = from.getInputStream();
        OutputStream out = to.getOutputStream();
        int count;
        while ((count = in.read(buffer)) != -1) out.write(buffer, 0, count);
        to.shutdownOutput();
    }

    private static void closeSocket(Socket socket) {
        try { socket.close(); } catch (IOException ignored) { }
    }

    @Override
    public void close() {
        synchronized (sockets) {
            if (closed) return;
            closed = true;
            try { listener.close(); } catch (IOException ignored) { }
            for (Socket socket : sockets) closeSocket(socket);
            workers.shutdownNow();
        }
    }
}
