# Agent Browser — Chrome for Testing in a container
# Image: ghcr.io/summitflow-solutions/agent-browser
# Provides isolated browser sessions for automated UI testing
#
# Usage: docker run --rm --shm-size=2gb ghcr.io/summitflow-solutions/agent-browser
# Exposes Chrome DevTools Protocol on port 9222

FROM node:20-slim

# Install Chrome for Testing and dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates fonts-liberation \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome for Testing via npx
RUN npx @puppeteer/browsers install chrome@stable \
    && npx @puppeteer/browsers install chromedriver@stable

# Create non-root user for Chrome
RUN groupadd -r browser && useradd -r -g browser -G audio,video browser \
    && mkdir -p /home/browser/Downloads \
    && chown -R browser:browser /home/browser

USER browser
WORKDIR /home/browser

ENV CHROME_FLAGS="--no-sandbox --disable-dev-shm-usage --disable-gpu --headless=new --remote-debugging-port=9222 --remote-debugging-address=0.0.0.0"

EXPOSE 9222

# Default: start Chrome in headless mode with remote debugging
CMD ["sh", "-c", "find /root -name 'chrome' -type f 2>/dev/null | head -1 | xargs -I{} {} $CHROME_FLAGS"]
