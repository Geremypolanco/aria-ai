# Deploy ARIA AI on Oracle Cloud Always Free (Ampere A1, ARM64)

Free-forever setup: 1× VM.Standard.A1.Flex (up to 4 OCPU / 24 GB RAM on the
Always Free tier) running Ubuntu 24.04, Docker, and this repo's containers.
The image builds natively for ARM64 on the VM — no cross-compilation needed.

## 1. Oracle Cloud account + VM

1. Create your Oracle Cloud account (Always Free; card verification, no charges).
2. Console → Compute → Instances → **Create instance**:
   - Image: **Ubuntu 24.04** (aarch64)
   - Shape: **VM.Standard.A1.Flex** → 4 OCPU, 24 GB RAM (within Always Free)
   - Add your SSH public key; keep the private key safe.
   - Under *Networking*, allow inbound **TCP 8080** (add an ingress rule for
     `0.0.0.0/0` on port 8080 in the subnet's security list, or attach an NSG
     with that rule).
3. SSH in: `ssh -i <key> ubuntu@<public-ip>`

## 2. Install Docker (Ubuntu 24.04)

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update && sudo apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER   # log out and back in afterwards
```

Ubuntu's own firewall: `sudo ufw allow 8080/tcp` (if ufw is enabled).

## 3. Get the code + secrets

```bash
git clone https://github.com/Geremypolanco/aria-ai.git
cd aria-ai
git checkout fix/launch-readiness
cp .env.example .env
nano .env   # fill in at minimum:
            # SUPABASE_URL, SUPABASE_KEY, one LLM key (HF_TOKEN),
            # ADMIN_PASSWORD, SESSION_SECRET
```

Before this, apply the SQL schemas in `database/` + `supabase_schema.sql`
to your Supabase project (Supabase dashboard → SQL editor).

## 4. Build & run

```bash
docker compose -f infra/oracle-cloud/docker-compose.yml up -d --build
```

First build takes several minutes (downloads the ARM64 Chromium for
Playwright). Then verify:

```bash
docker compose -f infra/oracle-cloud/docker-compose.yml ps
curl -f http://localhost:8080/health
```

Open `http://<public-ip>:8080` in a browser.

## 5. Updates

```bash
cd ~/aria-ai
git pull
docker compose -f infra/oracle-cloud/docker-compose.yml up -d --build
```

Redis data persists in the `redis_data` named volume across restarts.

## Troubleshooting

- **Port 8080 unreachable externally:** re-check the security-list ingress
  rule (Oracle side) and `sudo ufw status` (VM side).
- **Build OOM:** the A1 shape has plenty of RAM; if you chose a smaller
  shape, add swap (`sudo fallocate -l 4G /swapfile …`) before building.
- **Playwright errors at runtime:** the image installs the ARM64 Chromium
  build automatically; confirm with
  `docker compose -f infra/oracle-cloud/docker-compose.yml exec aria-api ls /ms-browsers`.
