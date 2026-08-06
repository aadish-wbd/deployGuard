[Unit]
Description=DeployGuard FastAPI service
After=network.target

[Service]
Type=simple
User=deployguard
Group=deployguard
WorkingDirectory=/opt/deployguard
EnvironmentFile=/etc/deployguard.env
ExecStart=/opt/deployguard/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=append:/var/log/deployguard/app.log
StandardError=append:/var/log/deployguard/app.log

[Install]
WantedBy=multi-user.target
