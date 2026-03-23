---
outline: [2, 3]
---

# Update System

Seamless software updates for both standalone and Docker installations.

## Features

- **GitHub API Integration**: Check for updates without requiring git repository
- **Version Management**: Semantic versioning via VERSION file
- **Docker Live-Updates**: Optional live-update mode for Docker containers
- **Automatic Backup**: Creates backup before applying updates
- **Branch Support**: Supports both main and master branches

## Updating via Web Interface

Navigate to the Configuration page in the web UI:

1. Click "Check for Updates"
2. Review available version
3. Click "Apply Update" to install
4. System creates automatic backup before updating

## Manual Updates

### Standalone Installation

```bash
# Pull latest changes
git pull origin main

# Install dependencies
pip install -r requirements.txt

# Restart service
python web_main.py
```

### Docker Installation

```bash
# Pull latest image
docker-compose pull

# Restart with new image
docker-compose up -d
```

### Docker Live-Update Mode

```bash
# Start live-update mode
docker-compose -f docker-compose.live-update.yml up -d

# This allows updating without downtime
```

## Rollback

If an update causes issues:

1. Access the backup via Configuration page
2. Click "Restore Backup" to revert
3. Or manually restore from the backup directory
