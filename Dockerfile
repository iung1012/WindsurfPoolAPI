FROM node:20-slim

# Tools needed to download and extract the LS binary from the Windsurf .deb
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates \
        && rm -rf /var/lib/apt/lists/*

        # Download Windsurf stable .deb and extract just the language_server binary.
        # Channel hash comes from the Windsurf stable apt repo URL.
        RUN set -eux; \
            CHANNEL="wVxQEIWkwPUEAGf3"; \
                APT_BASE="https://windsurf-stable.codeiumdata.com/${CHANNEL}/apt"; \
                    wget -qO /tmp/Packages.gz "${APT_BASE}/dists/stable/main/binary-amd64/Packages.gz"; \
                        cd /tmp && gunzip Packages.gz; \
                            DEB_REL=$(grep '^Filename:' /tmp/Packages | grep 'windsurf_' | head -1 | awk '{print $2}'); \
                                echo "Downloading: ${APT_BASE}/${DEB_REL}"; \
                                    wget -qO /tmp/windsurf.deb "${APT_BASE}/${DEB_REL}"; \
                                        mkdir -p /tmp/ws-extract /opt/windsurf; \
                                            dpkg-deb -x /tmp/windsurf.deb /tmp/ws-extract; \
                                                find /tmp/ws-extract -name 'language_server_linux_x64' -exec install -m755 {} /opt/windsurf/language_server_linux_x64 \;; \
                                                    rm -rf /tmp/Packages /tmp/windsurf.deb /tmp/ws-extract; \
                                                        echo "Language Server installed: $(ls -lh /opt/windsurf/)"

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
