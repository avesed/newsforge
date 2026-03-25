import { useTranslation } from "react-i18next";
import { Bookmark } from "lucide-react";

export default function BookmarksPage() {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold text-foreground">{t("bookmarks.title")}</h1>
      <div className="flex flex-col items-center justify-center py-16">
        <Bookmark className="mb-4 h-12 w-12 text-muted-foreground" />
        <p className="text-muted-foreground">{t("bookmarks.empty")}</p>
      </div>
    </div>
  );
}
