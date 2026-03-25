import { useTranslation } from "react-i18next";
import { useThemeStore } from "@/stores/themeStore";

export default function SettingsPage() {
  const { t, i18n } = useTranslation();
  const { theme, toggle: toggleTheme } = useThemeStore();

  const toggleLang = () => {
    const next = i18n.language === "zh" ? "en" : "zh";
    void i18n.changeLanguage(next);
    localStorage.setItem("language", next);
  };

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold text-foreground">{t("settings.title")}</h1>

      <div className="flex flex-col gap-3">
        {/* Language */}
        <div className="flex items-center justify-between rounded-lg border border-border bg-card p-4">
          <span className="font-medium text-foreground">{t("settings.language")}</span>
          <button
            onClick={toggleLang}
            className="rounded-md border border-border px-4 py-2 text-sm text-foreground hover:bg-accent"
          >
            {i18n.language === "zh" ? "English" : "\u4e2d\u6587"}
          </button>
        </div>

        {/* Theme */}
        <div className="flex items-center justify-between rounded-lg border border-border bg-card p-4">
          <span className="font-medium text-foreground">{t("settings.theme")}</span>
          <button
            onClick={toggleTheme}
            className="rounded-md border border-border px-4 py-2 text-sm text-foreground hover:bg-accent"
          >
            {theme === "dark" ? t("settings.themeLight") : t("settings.themeDark")}
          </button>
        </div>
      </div>
    </div>
  );
}
