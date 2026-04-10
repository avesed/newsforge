import { useState, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import {
  Upload,
  FileJson,
  CheckCircle2,
  AlertCircle,
  Loader2,
  X,
} from "lucide-react";
import { importArticles } from "@/api/admin";
import type { ImportResult } from "@/api/admin";
import { getErrorMessage } from "@/api/client";
import { AdminLayout } from "@/components/admin/AdminLayout";

interface FilePreview {
  name: string;
  size: number;
  articleCount: number | null;
  source: string | null;
  exportedAt: string | null;
}

export default function AdminImportPage() {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const importMutation = useMutation({
    mutationFn: importArticles,
    onSuccess: (data) => {
      setResult(data);
    },
  });

  const parseFile = useCallback(async (file: File) => {
    setParseError(null);
    setResult(null);

    if (!file.name.endsWith(".json")) {
      setParseError(t("admin.import.invalidFileType"));
      return;
    }

    const MAX_FILE_SIZE = 500 * 1024 * 1024; // 500 MB
    if (file.size > MAX_FILE_SIZE) {
      setParseError(t("admin.import.fileTooLarge"));
      return;
    }

    try {
      // For large files (>20MB), only read the header to extract metadata
      // and skip full client-side JSON parsing to avoid browser freeze
      const PARSE_THRESHOLD = 20 * 1024 * 1024;
      if (file.size > PARSE_THRESHOLD) {
        // Read first 4KB to extract count/source/exported_at from header
        const headerText = await file.slice(0, 4096).text();
        const countMatch = headerText.match(/"count"\s*:\s*(\d+)/);
        const sourceMatch = headerText.match(/"source"\s*:\s*"([^"]+)"/);
        const exportedMatch = headerText.match(/"exported_at"\s*:\s*"([^"]+)"/);

        if (!headerText.includes('"articles"')) {
          setParseError(t("admin.import.invalidFormat"));
          return;
        }

        setSelectedFile(file);
        setPreview({
          name: file.name,
          size: file.size,
          articleCount: countMatch?.[1] ? parseInt(countMatch[1], 10) : null,
          source: sourceMatch?.[1] ?? null,
          exportedAt: exportedMatch?.[1] ?? null,
        });
      } else {
        const text = await file.text();
        const data = JSON.parse(text);

        if (!data.articles || !Array.isArray(data.articles)) {
          setParseError(t("admin.import.invalidFormat"));
          return;
        }

        setSelectedFile(file);
        setPreview({
          name: file.name,
          size: file.size,
          articleCount: data.count ?? data.articles.length,
          source: data.source ?? null,
          exportedAt: data.exported_at ?? null,
        });
      }
    } catch {
      setParseError(t("admin.import.parseError"));
    }
  }, [t]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragActive(false);
      const file = e.dataTransfer.files[0];
      if (file) parseFile(file);
    },
    [parseFile],
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) parseFile(file);
    },
    [parseFile],
  );

  const handleImport = () => {
    if (selectedFile) {
      importMutation.mutate(selectedFile);
    }
  };

  const handleClear = () => {
    setSelectedFile(null);
    setPreview(null);
    setParseError(null);
    setResult(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <AdminLayout>
      <div className="space-y-6">
        <div>
          <h2 className="text-lg font-semibold text-foreground">
            {t("admin.import.title")}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("admin.import.description")}
          </p>
        </div>

        {/* Drop zone */}
        {!preview && !result && (
          <div
            role="button"
            tabIndex={0}
            aria-label={t("admin.import.dropzoneLabel")}
            className={`relative rounded-lg border-2 border-dashed p-12 text-center transition-colors ${
              dragActive
                ? "border-primary bg-primary/5"
                : "border-muted-foreground/25 hover:border-muted-foreground/50"
            }`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
          >
            <Upload className="mx-auto h-10 w-10 text-muted-foreground" />
            <p className="mt-3 text-sm font-medium text-foreground">
              {t("admin.import.dropzone")}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("admin.import.dropzoneHint")}
            </p>
            <button
              type="button"
              className="mt-4 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              onClick={() => fileInputRef.current?.click()}
            >
              {t("admin.import.selectFile")}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={handleFileInput}
            />
          </div>
        )}

        {/* Parse error */}
        {parseError && (
          <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {parseError}
          </div>
        )}

        {/* File preview */}
        {preview && !result && (
          <div className="rounded-lg border border-border bg-card p-6 space-y-4">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <FileJson className="h-8 w-8 text-primary" />
                <div>
                  <p className="font-medium text-foreground">{preview.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatSize(preview.size)}
                    {preview.source && ` \u00b7 ${t("admin.import.source")}: ${preview.source}`}
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground"
                onClick={handleClear}
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <div>
                <p className="text-xs text-muted-foreground">
                  {t("admin.import.articleCount")}
                </p>
                <p className="text-lg font-semibold text-foreground">
                  {preview.articleCount?.toLocaleString() ?? "?"}
                </p>
              </div>
              {preview.exportedAt && (
                <div>
                  <p className="text-xs text-muted-foreground">
                    {t("admin.import.exportedAt")}
                  </p>
                  <p className="text-sm text-foreground">
                    {new Date(preview.exportedAt).toLocaleString()}
                  </p>
                </div>
              )}
            </div>

            <button
              type="button"
              className="flex items-center gap-2 rounded-md bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              onClick={handleImport}
              disabled={importMutation.isPending}
            >
              {importMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("admin.import.importing")}
                </>
              ) : (
                <>
                  <Upload className="h-4 w-4" />
                  {t("admin.import.startImport")}
                </>
              )}
            </button>

            {importMutation.isError && (
              <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {getErrorMessage(importMutation.error)}
              </div>
            )}
          </div>
        )}

        {/* Results */}
        {result && (
          <div aria-live="polite" className="rounded-lg border border-border bg-card p-6 space-y-4">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
              <h3 className="font-semibold text-foreground">
                {t("admin.import.complete")}
              </h3>
            </div>

            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatItem
                label={t("admin.import.total")}
                value={result.total.toLocaleString()}
              />
              <StatItem
                label={t("admin.import.imported")}
                value={result.imported.toLocaleString()}
                variant="success"
              />
              <StatItem
                label={t("admin.import.duplicatesSkipped")}
                value={result.duplicates.toLocaleString()}
              />
              <StatItem
                label={t("admin.import.errorsCount")}
                value={result.errors.toLocaleString()}
                variant={result.errors > 0 ? "destructive" : "default"}
              />
            </div>

            {result.errorDetails.length > 0 && (
              <div className="rounded-md border border-destructive/20 bg-destructive/5 p-3">
                <p className="mb-2 text-xs font-medium text-destructive">
                  {t("admin.import.errorDetails")}
                </p>
                <ul className="space-y-1 text-xs text-destructive/80">
                  {result.errorDetails.map((detail, i) => (
                    <li key={i}>{detail}</li>
                  ))}
                </ul>
              </div>
            )}

            <button
              type="button"
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              onClick={handleClear}
            >
              {t("admin.import.importAnother")}
            </button>
          </div>
        )}
      </div>
    </AdminLayout>
  );
}

function StatItem({
  label,
  value,
  variant = "default",
}: {
  readonly label: string;
  readonly value: string;
  readonly variant?: "default" | "success" | "destructive";
}) {
  const colorClass =
    variant === "success"
      ? "text-green-600 dark:text-green-400"
      : variant === "destructive"
        ? "text-destructive"
        : "";

  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-lg font-semibold ${colorClass}`}>{value}</p>
    </div>
  );
}
