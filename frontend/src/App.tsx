import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Layout } from "@/components/layout/Layout";
import { Toaster } from "@/components/ui/Toast";
import { useAuthStore } from "@/stores/authStore";

const HomePage = lazy(() => import("@/pages/HomePage"));
const CategoryPage = lazy(() => import("@/pages/CategoryPage"));
const ArticlePage = lazy(() => import("@/pages/ArticlePage"));
const SearchPage = lazy(() => import("@/pages/SearchPage"));
const LoginPage = lazy(() => import("@/pages/LoginPage"));
const RegisterPage = lazy(() => import("@/pages/RegisterPage"));
const BookmarksPage = lazy(() => import("@/pages/BookmarksPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));
const AdminOverviewPage = lazy(() => import("@/pages/admin/AdminOverviewPage"));
const AdminFeedsPage = lazy(() => import("@/pages/admin/AdminFeedsPage"));
const AdminConsumersPage = lazy(() => import("@/pages/admin/AdminConsumersPage"));
const AdminLLMPage = lazy(() => import("@/pages/admin/AdminLLMPage"));
const AdminPipelinePage = lazy(() => import("@/pages/admin/AdminPipelinePage"));
const AdminImportPage = lazy(() => import("@/pages/admin/AdminImportPage"));
const AdminUsersPage = lazy(() => import("@/pages/admin/AdminUsersPage"));
const ReadingHistoryPage = lazy(() => import("@/pages/ReadingHistoryPage"));
const StoriesPage = lazy(() => import("./pages/StoriesPage"));
const StoryDetailPage = lazy(() => import("@/pages/StoryDetailPage"));

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center py-12">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuthStore();
  if (isLoading) return <LoadingFallback />;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuthStore();
  if (isLoading) return <LoadingFallback />;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "admin") return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<LoadingFallback />}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/news/:category" element={<CategoryPage />} />
            <Route path="/article/:id" element={<ArticlePage />} />
            <Route path="/stories" element={<StoriesPage />} />
            <Route path="/stories/:id" element={<StoryDetailPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route
              path="/bookmarks"
              element={
                <RequireAuth>
                  <BookmarksPage />
                </RequireAuth>
              }
            />
            <Route
              path="/history"
              element={
                <RequireAuth>
                  <ReadingHistoryPage />
                </RequireAuth>
              }
            />
            <Route
              path="/settings"
              element={
                <RequireAuth>
                  <SettingsPage />
                </RequireAuth>
              }
            />
            <Route
              path="/admin"
              element={
                <RequireAdmin>
                  <AdminOverviewPage />
                </RequireAdmin>
              }
            />
            <Route
              path="/admin/feeds"
              element={
                <RequireAdmin>
                  <AdminFeedsPage />
                </RequireAdmin>
              }
            />
            <Route
              path="/admin/consumers"
              element={
                <RequireAdmin>
                  <AdminConsumersPage />
                </RequireAdmin>
              }
            />
            <Route
              path="/admin/llm"
              element={
                <RequireAdmin>
                  <AdminLLMPage />
                </RequireAdmin>
              }
            />
            <Route
              path="/admin/pipeline"
              element={
                <RequireAdmin>
                  <AdminPipelinePage />
                </RequireAdmin>
              }
            />
            <Route
              path="/admin/users"
              element={
                <RequireAdmin>
                  <AdminUsersPage />
                </RequireAdmin>
              }
            />
            <Route
              path="/admin/import"
              element={
                <RequireAdmin>
                  <AdminImportPage />
                </RequireAdmin>
              }
            />
          </Route>
        </Routes>
      </Suspense>
      <Toaster />
    </BrowserRouter>
  );
}
