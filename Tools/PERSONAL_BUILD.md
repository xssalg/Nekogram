# Personal APK

Branch `custom/noads-http` disables fetching sponsored messages in channels and bot chats and sponsored search results, and stops fetching promoted proxy channels. Ordinary channel posts and bot messages remain visible.

Settings → Data and Storage → Proxy Settings → Add Proxy → **HTTP CONNECT** accepts a proxy host, port and optional Basic username/password. HTTP CONNECT is a TCP proxy, distinct from Telegram Web Proxy and HTTPS-to-proxy. Import/export uses the custom `tg://httpproxy?server=HOST&port=PORT&user=USER&pass=PASSWORD` URI supported by this build. The localhost bridge requires a random per-instance password and never falls back to a direct connection.

GitHub Actions builds a signed ARM64 release APK under application ID `tw.nekomimi.nekogram.personal`, which can be installed alongside official Nekogram. The signing key is stored in repository Actions secrets `NEKO_CUSTOM_KEYSTORE` and `NEKO_CUSTOM_KEYSTORE_PASSWORD`; keep it to sign compatible future updates. No Firebase credentials are included, so Firebase push and analytics are unavailable. Telegram's public Android sample API credentials are used unless `API_ID` and `API_HASH` repository secrets are configured. Google Maps requires a separately configured API key.

Run `python3 Tools/test_http_proxy.py` with JDK 21 to test actual socket transport against local proxy fixtures. Device login and a real user-supplied proxy require a device smoke test after installing.
