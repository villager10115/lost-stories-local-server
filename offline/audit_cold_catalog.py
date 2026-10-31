import base64
import json
from pathlib import Path
import re

root = Path('D:/LostStories_Offline/assets/native-catalogs-18865')
for p in root.glob('*.json'):
    d = json.loads(p.read_text('utf-8-sig'))
    print(p.name, list(d))
    for key, value in d.items():
        if isinstance(value, str) and key.endswith('String'):
            try:
                raw = base64.b64decode(value)
                matches = re.findall(rb'https?[^\x00\s"<>]{6,180}', raw)
                wide = re.findall(r'https?[^\s"<>]{6,180}', raw.decode('utf-16le', 'ignore'))
                print(key, 'URL counts', len(matches), len(wide), 'examples', matches[:2], wide[:2])
            except Exception:
                pass
        elif isinstance(value, list) and ('url' in key.lower() or 'object' in key.lower()):
            print(key, len(value), value[:2])
