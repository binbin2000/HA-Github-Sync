FROM alpine:3.22
RUN apk add --no-cache bash ca-certificates git openssh-client-default python3 py3-yaml py3-pip tzdata \
    && python3 -m pip install --no-cache-dir --target /opt/ha-cron 'croniter==6.2.4'
WORKDIR /opt/ha-github-sync
COPY git_sync.sh sync_*.py app_runner.py ./
ENV PYTHONPATH=/opt/ha-cron PYTHONDONTWRITEBYTECODE=1
CMD ["python3", "-u", "/opt/ha-github-sync/app_runner.py"]
