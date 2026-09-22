// Скопируйте в shiki_config.js и впишите данные своего OAuth-приложения Shikimori
// (https://shikimori.io/oauth/applications → «Новое приложение», Redirect URI: urn:ietf:wg:oauth:2.0:oob,
// права: user_rates, comments). shiki_config.js не хранится в git.
export default {
  clientId: "",
  clientSecret: "",
  appName: "AnimeApp",  // название приложения на Shikimori — отправляется в User-Agent
};
