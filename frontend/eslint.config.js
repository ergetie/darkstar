import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-plugin-prettier/recommended'; // Use recommended helper

export default tseslint.config(
    { ignores: ['dist', '.eslintrc.cjs', 'src/pages/archive/**'] },
    {
        extends: [
            js.configs.recommended,
            ...tseslint.configs.recommended,
            prettier, // Combines "extends config" and "plugin rules"
        ],
        files: ['**/*.{ts,tsx}'],
        languageOptions: {
            ecmaVersion: 2020,
            globals: globals.browser,
        },
        plugins: {
            'react-hooks': reactHooks,
            'react-refresh': reactRefresh,
        },
        rules: {
            ...reactHooks.configs.recommended.rules,
            'react-refresh/only-export-components': [
                'warn',
                { allowConstantExport: true },
            ],
            '@typescript-eslint/no-explicit-any': 'warn', // Warn on accidental any usage
            '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
            'react-hooks/exhaustive-deps': 'warn',
        },
    },
);
