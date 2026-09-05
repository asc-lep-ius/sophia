import js from "@eslint/js";
import svelte from "eslint-plugin-svelte";
import globals from "globals";
import tseslint from "typescript-eslint";

export default [
  {
    ignores: [
      ".svelte-kit/**",
      "build/**",
      "node_modules/**",
      "playwright-report/**",
      "src/lib/api/schema.d.ts",
      "src/lib/paraglide/**",
      "test-results/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...svelte.configs["flat/recommended"],
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
      parserOptions: {
        extraFileExtensions: [".svelte"],
      },
    },
  },
  {
    // .svelte.ts modules go through svelte-eslint-parser, which needs the
    // TypeScript parser handed to it the same way .svelte files do.
    files: ["**/*.svelte", "**/*.svelte.ts", "**/*.svelte.js"],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
      },
    },
  },
];
