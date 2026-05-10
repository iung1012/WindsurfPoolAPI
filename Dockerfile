FROM node:20-slim

# Tools to set up apt source and extract the LS binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates \
        && rm -rf /var/lib/apt/lists/*

        # Add Windsurf apt repo (trusted=yes skips GPG, avoids needing gnupg)
        # then download the .deb without installing, extract just the language_server binary.
        RUN set -eux; \
            echo "deb [arch=amd64 trusted=yes] https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/apt stable main" \
                    > /etc/apt/sources.list.d/windsurf.list; \
                        apt-get update; \
                            mkdir -p /tmp/ws-dl && cd /tmp/ws-dl; \
                                apt-get download windsurf; \
                                    dpkg-deb -x /tmp/ws-dl/windsurf_*.deb /tmp/ws-extract; \
                                        mkdir -p /opt/windsurf; \
                                            find /tmp/ws-extract -name 'language_server_linux_x64' \
                                                    -exec install -m755 {} /opt/windsurf/language_server_linux_x64 \;; \
                                                        rm -rf /tmp/ws-dl /tmp/ws-extract; \
                                                            echo "Done: $(ls -lh /opt/windsurf/)"

                                                            RUN addgroup --system app && adduser --system app --ingroup app

                                                            WORKDIR /app

                                                            COPY --chown=app:app package.json ./
                                                            COPY --chown=app:app src ./src
                                                            COPY --chown=app:app docs ./docs

                                                            RUN chown -R app:app /opt/windsurf

                                                            ENV LS_BINARY_PATH=/opt/windsurf/language_server_linux_x64
                                                            ENV PORT=3003
                                                            ENV LS_PORT=42100
                                                            ENV LOG_LEVEL=info

                                                            RUN mkdir -p /app/logs /tmp/windsurf-workspace \
                                                                && chown -R app:app /app /tmp/windsurf-workspace

                                                                USER app

                                                                EXPOSE 3003

                                                                HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
                                                                    CMD wget -qO- http://127.0.0.1:3003/health || exit 1

                                                                    CMD ["node", "src/index.js"]
