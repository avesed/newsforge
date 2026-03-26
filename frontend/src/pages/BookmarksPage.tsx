import { useTranslation } from "react-i18next";
import { Bookmark } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";

export default function BookmarksPage() {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold text-foreground">{t("bookmarks.title")}</h1>
      <EmptyState
        icon={Bookmark}
        title={t("bookmarks.empty")}
        description={t("bookmarks.emptyHint")}
      />
    </div>
  );
}
