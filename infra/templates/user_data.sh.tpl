#!/bin/bash
set -euxo pipefail

APP_DIR="/opt/deployguard"
APP_USER="deployguard"
LOG_GROUP="${log_group_name}"

exec > >(tee /var/log/deployguard-bootstrap.log) 2>&1

# --- Packages (standard Amazon Linux 2023 — not Minimal) ---
dnf update -y
dnf install -y python3 python3-pip git amazon-cloudwatch-agent

# --- App user (no home dir yet — avoids git clone "destination exists" error) ---
id -u "$APP_USER" &>/dev/null || useradd -r -s /sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR" /var/log/deployguard
chown "$APP_USER:$APP_USER" /var/log/deployguard

# --- Clone repo (initial bootstrap) ---
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "${git_branch}" "${git_repo_url}" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# --- Python venv + deps ---
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# --- Dashboard UI (Node.js build) ---
dnf install -y nodejs npm
mkdir -p "$APP_DIR/.npm-cache"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/.npm-cache"
cd "$APP_DIR/frontend"
sudo -u "$APP_USER" bash -lc "export HOME=$APP_DIR NPM_CONFIG_CACHE=$APP_DIR/.npm-cache; npm install && npm run build"
cd "$APP_DIR"

# --- Environment file (non-secrets; secrets loaded from Secrets Manager at runtime) ---
cat > /etc/deployguard.env << 'ENVEOF'
${env_file_content}
ENVEOF
chmod 640 /etc/deployguard.env
chown root:"$APP_USER" /etc/deployguard.env

usermod -d "$APP_DIR" "$APP_USER" 2>/dev/null || true

# --- systemd service ---
cat > /etc/systemd/system/deployguard.service << 'SVCEOF'
${systemd_unit_content}
SVCEOF

systemctl daemon-reload
systemctl enable deployguard
systemctl restart deployguard

# --- CloudWatch Agent (app logs) ---
mkdir -p /opt/aws/amazon-cloudwatch-agent/etc
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << CWEOF
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/deployguard/app.log",
            "log_group_name": "${log_group_name}",
            "log_stream_name": "{instance_id}/deployguard",
            "timezone": "UTC"
          }
        ]
      }
    }
  }
}
CWEOF

/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json -s || true

echo "DeployGuard bootstrap complete"
