import { readFile } from "node:fs/promises";

const locales = ["en", "de"];
const messages = await Promise.all(
  locales.map(async (locale) => [
    locale,
    JSON.parse(
      await readFile(
        new URL(`../messages/${locale}.json`, import.meta.url),
        "utf8",
      ),
    ),
  ]),
);

const visibleKeys = (value) =>
  Object.keys(value)
    .filter((key) => !key.startsWith("$"))
    .sort();
const [baseLocale, baseMessages] = messages[0];
const baseKeys = visibleKeys(baseMessages);

for (const [locale, localeMessages] of messages.slice(1)) {
  const keys = visibleKeys(localeMessages);
  const missing = baseKeys.filter((key) => !keys.includes(key));
  const extra = keys.filter((key) => !baseKeys.includes(key));
  if (missing.length || extra.length) {
    throw new Error(
      `${locale} message keys differ from ${baseLocale}. Missing: ${missing.join(", ") || "-"}; extra: ${extra.join(", ") || "-"}`,
    );
  }
}
