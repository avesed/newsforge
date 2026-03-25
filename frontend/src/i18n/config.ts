import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en/common.json";
import zh from "./locales/zh/common.json";

const savedLang = localStorage.getItem("language") ?? "zh";

void i18n.use(initReactI18next).init({
  resources: {
    en: { common: en },
    zh: { common: zh },
  },
  lng: savedLang,
  fallbackLng: "zh",
  defaultNS: "common",
  ns: ["common"],
  interpolation: {
    escapeValue: false,
  },
});

export default i18n;
