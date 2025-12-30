#!/usr/bin/env node
/**
 * Extract help text from config.default.yaml comments
 * Output: frontend/src/config-help.json
 */

const fs = require('fs');
const path = require('path');

const CONFIG_FILE = path.join(__dirname, '..', 'config.default.yaml');
const OUTPUT_FILE = path.join(__dirname, '..', 'frontend', 'src', 'config-help.json');

function extractConfigHelp() {
    console.log('Extracting help text from config.default.yaml...');

    const content = fs.readFileSync(CONFIG_FILE, 'utf-8');
    const lines = content.split('\n');

    const helpMap = {};
    let currentComment = [];
    let currentPath = [];

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trim();

        // Skip empty lines and header comments
        if (!trimmed || trimmed.startsWith('# ===')) {
            currentComment = [];
            continue;
        }

        // Collect comment lines
        if (trimmed.startsWith('#')) {
            const comment = trimmed.substring(1).trim();
            if (comment) {
                currentComment.push(comment);
            }
            continue;
        }

        // Parse key: value lines
        const match = line.match(/^(\s*)([a-z_]+):/);
        if (match) {
            const indent = match[1].length;
            const key = match[2];

            // Calculate nesting level
            const level = indent / 2;
            currentPath = currentPath.slice(0, level);
            currentPath.push(key);

            // Store help text if we have comments
            if (currentComment.length > 0) {
                const fullKey = currentPath.join('.');
                helpMap[fullKey] = currentComment.join(' ');
                currentComment = [];
            }
        }
    }

    // Write output
    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(helpMap, null, 2), 'utf-8');
    console.log(`✓ Extracted ${Object.keys(helpMap).length} help entries to ${OUTPUT_FILE}`);
}

extractConfigHelp();
