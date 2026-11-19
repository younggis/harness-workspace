# Runtime image: fixed non-root UID, locked dsh version, no platform secrets.
FROM node:24-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DSH_HOME=/dsh-home \
    PNPM_HOME=/pnpm
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 harness && useradd -u 10001 -g harness -m -d /dsh-home harness \
    && mkdir -p /workspace /dsh-home /opt/harness \
    && chown -R 10001:10001 /workspace /dsh-home /opt/harness \
    && corepack enable

# Locked dsh release: never an unlocked runtime npx install.
RUN npm install -g @deepseek-ai/dsh@0.2.2-rc.4 \
    && pip3 install --no-cache-dir --break-system-packages \
      fastapi==0.115.6 uvicorn==0.34.0 httpx==0.28.1 websockets==14.1 pydantic==2.10.4

COPY runtime/base/entrypoint.py runtime/base/adapter.py runtime/base/fileservice.py runtime/base/ptyservice.py /opt/harness/
COPY runtime/base/profile/ /opt/harness/profile/
RUN chown -R 10001:10001 /opt/harness

USER 10001:10001
ENV PYTHONPATH=/opt/harness
WORKDIR /workspace
EXPOSE 8080
CMD ["python3", "/opt/harness/entrypoint.py"]
