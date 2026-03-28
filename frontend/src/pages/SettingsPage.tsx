import { useTranslation } from "react-i18next";
import { useThemeStore } from "@/stores/themeStore";
import { useReadingStore } from "@/stores/readingStore";
import { cn } from "@/lib/utils";

function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" className="flex rounded-lg border border-border overflow-hidden">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          aria-pressed={value === opt.value}
          className={cn(
            "px-3 py-1.5 text-sm font-medium transition-colors",
            value === opt.value
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export default function SettingsPage() {
  const { t, i18n } = useTranslation();
  const { theme, toggle: toggleTheme } = useThemeStore();
  const {
    fontSize,
    lineSpacing,
    contentWidth,
    setFontSize,
    setLineSpacing,
    setContentWidth,
  } = useReadingStore();

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

      {/* Reading Preferences */}
      <h2 className="mt-4 text-lg font-semibold text-foreground">
        {t("settings.readingPreferences")}
      </h2>

      <div className="flex flex-col gap-3">
        {/* Font Size */}
        <div className="flex items-center justify-between rounded-lg border border-border bg-card p-4">
          <span className="font-medium text-foreground">{t("settings.fontSize")}</span>
          <SegmentedControl
            value={fontSize}
            onChange={setFontSize}
            options={[
              { value: "sm", label: t("settings.fontSizeSm") },
              { value: "base", label: t("settings.fontSizeBase") },
              { value: "lg", label: t("settings.fontSizeLg") },
              { value: "xl", label: t("settings.fontSizeXl") },
            ]}
          />
        </div>

        {/* Line Spacing */}
        <div className="flex items-center justify-between rounded-lg border border-border bg-card p-4">
          <span className="font-medium text-foreground">{t("settings.lineSpacing")}</span>
          <SegmentedControl
            value={lineSpacing}
            onChange={setLineSpacing}
            options={[
              { value: "normal", label: t("settings.lineSpacingNormal") },
              { value: "relaxed", label: t("settings.lineSpacingRelaxed") },
              { value: "loose", label: t("settings.lineSpacingLoose") },
            ]}
          />
        </div>

        {/* Content Width */}
        <div className="flex items-center justify-between rounded-lg border border-border bg-card p-4">
          <span className="font-medium text-foreground">{t("settings.contentWidth")}</span>
          <SegmentedControl
            value={contentWidth}
            onChange={setContentWidth}
            options={[
              { value: "narrow", label: t("settings.contentWidthNarrow") },
              { value: "default", label: t("settings.contentWidthDefault") },
              { value: "wide", label: t("settings.contentWidthWide") },
            ]}
          />
        </div>
      </div>
    </div>
  );
}
