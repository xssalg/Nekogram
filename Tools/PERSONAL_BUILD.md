# Personal APK

Branch `custom/noads-http` disables fetching sponsored messages in channels and bot chats and sponsored search results and video overlays, and stops fetching promoted proxy channels. Ordinary channel posts and bot messages remain visible.

Settings → Data and Storage → Proxy Settings → Add Proxy → **HTTP CONNECT** accepts a proxy host, port and optional Basic username/password. HTTP CONNECT is a TCP proxy, distinct from Telegram Web Proxy and HTTPS-to-proxy. Import/export uses the custom `tg://httpproxy?server=HOST&port=PORT&user=USER&pass=PASSWORD` URI supported by this build. The localhost bridge requires a random per-instance password and never falls back to a direct connection.

GitHub Actions builds a signed ARM64 release APK under application ID `tw.nekomimi.nekogram.personal`, which can be installed alongside official Nekogram. The signing key is stored in repository Actions secrets `NEKO_CUSTOM_KEYSTORE` and `NEKO_CUSTOM_KEYSTORE_PASSWORD`; keep it to sign compatible future updates. No Firebase credentials are included, so Firebase push and analytics are unavailable. Configure your own `API_ID` and `API_HASH` repository secrets from https://my.telegram.org. Both are required; the published Android sample API credentials are rejected because the delivered fix1 APK returned `API_ID_PUBLISHED_FLOOD` during a real QR-login test. Google Maps requires a separately configured API key.

The manual workflow can test an existing APK by run ID and expected checksum, or build a new APK with `verify_login` enabled. Its QR test uses a temporary `NEKO_QR_CHECK_PROXY` JSON secret containing `host`, `port`, `user`, and `password`, imports that proxy through the app UI, and decodes a real `tg://login?token=...` from the screen. A QR-like loading animation does not pass. The test never submits a phone number or authorizes an account; delete the temporary proxy secret after the run. Missing or invalid API credentials stop a new build before compilation.

Run `python3 Tools/test_http_proxy.py` with JDK 21 to test actual socket transport against local proxy fixtures. Device login and a real user-supplied proxy require a device smoke test after installing.

## Startup signature configuration

The native JNI loader verifies the APK signing certificate before registering native functions. Personal builds derive `nativeCertHash` and `nativeCertSize` from their actual signing key and pass those plus the application ID to the native build. Leaving the upstream certificate constants with a personal signing key causes the process to receive SIGKILL during native loading and can leave the launch logo visible.

CI executes the production certificate parser and signature guard on the signed APK. The configured certificate must pass, and a mutated certificate must be rejected. The host fixture changes only descriptor path reporting and records process termination requests. This does not replace an Android device launch test.
