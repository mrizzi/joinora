import js from "@eslint/js";
import globals from "globals";

export default [
    js.configs.recommended,
    {
        files: ["conducere/frontend/**/*.js"],
        languageOptions: {
            ecmaVersion: 2020,
            sourceType: "script",
            globals: {
                ...globals.browser,
                marked: "readonly",
            },
        },
        rules: {
            "no-unused-vars": ["error", { varsIgnorePattern: "^_" }],
        },
    },
];
