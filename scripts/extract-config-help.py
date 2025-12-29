#!/usr/bin/env python3
"""
Extract help text from config.default.yaml comments
Output: frontend/src/config-help.json
"""

import json
import re
from pathlib import Path

CONFIG_FILE = Path(__file__).parent.parent / 'config.default.yaml'
OUTPUT_FILE = Path(__file__).parent.parent / 'frontend' / 'src' / 'config-help.json'

def extract_config_help():
    print('Extracting help text from config.default.yaml...')
    
    with open(CONFIG_FILE, 'r') as f:
        lines = f.readlines()
    
    help_map = {}
    current_comment = []
    current_path = []
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines and header comments
        if not stripped or stripped.startswith('# ==='):
            current_comment = []
            continue
        
        # Collect comment lines
        if stripped.startswith('#'):
            comment = stripped[1:].strip()
            if comment:
                current_comment.append(comment)
            continue
        
        # Parse key: value lines
        match = re.match(r'^(\s*)([a-z_]+):', line)
        if match:
            indent = len(match.group(1))
            key = match.group(2)
            
            # Calculate nesting level
            level = indent // 2
            current_path = current_path[:level]
            current_path.append(key)
            
            # Store help text if we have comments
            if current_comment:
                full_key = '.'.join(current_path)
                help_map[full_key] = ' '.join(current_comment)
                current_comment = []
    
    # Write output
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(help_map, f, indent=2)
    
    print(f'✓ Extracted {len(help_map)} help entries to {OUTPUT_FILE}')

if __name__ == '__main__':
    extract_config_help()
