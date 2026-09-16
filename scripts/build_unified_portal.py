"""Copy the reviewed shared frontend to the Worker assets directory."""
from pathlib import Path
import shutil
root=Path(__file__).resolve().parent.parent
destination=root/'cloudflare/public'
destination.mkdir(parents=True,exist_ok=True)
for name in ('index.html','app.js','styles.css','monitoring.css','portal-bridge.js','portal.css','crypto-ai-trader-icon.png','manifest.webmanifest','service-worker.js'):
    shutil.copy2(root/'web'/name,destination/name)
print('Shared portal assets built; no live installation changed.')
