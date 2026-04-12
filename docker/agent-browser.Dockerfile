# Agent Browser — Chrome for Testing in a container
# Image: ghcr.io/elias-leslie/agent-browser
# Provides isolated browser sessions for automated UI testing
#
# Usage: docker run --rm --shm-size=2gb ghcr.io/elias-leslie/agent-browser
# Exposes Chrome DevTools Protocol on port 9222

FROM node:20-slim

# Install Chrome for Testing system deps per Puppeteer Linux guidance for Debian Bookworm;
# validated here against Chrome for Testing stable 146.x on node:20-slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl fonts-liberation gnupg \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdbus-1-3 libdrm2 libgbm1 libglib2.0-0 libgtk-3-0 \
    libharfbuzz0b libnspr4 libnss3 libpango-1.0-0 \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 \
    libxdamage1 libxext6 libxfixes3 libxi6 libxrandr2 \
    libxrender1 libxss1 libxtst6 socat wget xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome for Testing, resolve binary path, clean caches in same layer
RUN npx @puppeteer/browsers install chrome@stable \
    && npx @puppeteer/browsers install chromedriver@stable \
    && CHROME_BIN=$(find / -name 'chrome' -type f -path '*/chrome-linux64/*' 2>/dev/null | head -1) \
    && ln -s "$CHROME_BIN" /usr/local/bin/chrome \
    && npm cache clean --force && rm -rf /tmp/* /root/.npm

# Create non-root user for Chrome
RUN groupadd -r browser && useradd -r -g browser -G audio,video browser \
    && mkdir -p /home/browser/Downloads \
    && chown -R browser:browser /home/browser

USER browser
WORKDIR /home/browser

EXPOSE 9222

# socat proxies CDP from 0.0.0.0:9222 to Chrome's localhost:9223
# (Chrome ignores --remote-debugging-address in newer versions)
CMD ["sh", "-c", "chrome --no-sandbox --disable-dev-shm-usage --disable-gpu --headless=new --remote-debugging-port=9223 --remote-allow-origins=* & sleep 2 && socat TCP-LISTEN:9222,fork,reuseaddr TCP:127.0.0.1:9223"]
