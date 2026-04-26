import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2, ShieldCheck, User as UserIcon } from "lucide-react";
import { AdminLayout } from "@/components/admin/AdminLayout";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { getUsers, updateUser, deleteUser, type UserRaw } from "@/api/admin";
import { getErrorMessage } from "@/api/client";
import { useAuthStore } from "@/stores/authStore";

function UsersContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((s) => s.user);
  const [error, setError] = useState("");

  const { data: users, isLoading } = useQuery({
    queryKey: ["admin", "users"],
    queryFn: getUsers,
    staleTime: 30_000,
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof updateUser>[1] }) =>
      updateUser(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      setError("");
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteUser,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      setError("");
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const handleRoleToggle = (user: UserRaw) => {
    if (user.id === currentUser?.id) return;
    const newRole = user.role === "admin" ? "user" : "admin";
    updateMutation.mutate({ id: user.id, data: { role: newRole } });
  };

  const handleActiveToggle = (user: UserRaw) => {
    if (user.id === currentUser?.id) return;
    updateMutation.mutate({ id: user.id, data: { isActive: !user.isActive } });
  };

  const handleDelete = (user: UserRaw) => {
    if (user.id === currentUser?.id) return;
    if (!confirm(t("admin.confirmDeleteUser"))) return;
    deleteMutation.mutate(user.id);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-foreground">
        {t("admin.userManagement")}
      </h2>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/50 p-3">
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        </div>
      )}

      {!users || users.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          {t("admin.noUsers")}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50">
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                  {t("admin.userEmail")}
                </th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                  {t("admin.userDisplayName")}
                </th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                  {t("admin.userRole")}
                </th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                  {t("admin.userStatus")}
                </th>
                <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                  {t("admin.userCreatedAt")}
                </th>
                <th className="px-4 py-3 text-right font-medium text-muted-foreground" />
              </tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const isSelf = user.id === currentUser?.id;
                return (
                  <tr
                    key={user.id}
                    className="border-b border-border last:border-b-0 hover:bg-muted/30"
                  >
                    <td className="px-4 py-3 font-medium">
                      <div className="flex items-center gap-2">
                        {user.role === "admin" ? (
                          <ShieldCheck className="h-4 w-4 text-primary shrink-0" />
                        ) : (
                          <UserIcon className="h-4 w-4 text-muted-foreground shrink-0" />
                        )}
                        <span className="truncate">{user.email}</span>
                        {isSelf && (
                          <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                            you
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {user.displayName || "—"}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => handleRoleToggle(user)}
                        disabled={isSelf || updateMutation.isPending}
                        className="cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                        title={isSelf ? t("admin.cannotModifySelf") : undefined}
                      >
                        <StatusBadge
                          status={user.role === "admin" ? t("admin.roleAdmin") : t("admin.roleUser")}
                          className={user.role === "admin" ? "bg-primary/10 text-primary dark:bg-primary/20" : ""}
                        />
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => handleActiveToggle(user)}
                        disabled={isSelf || updateMutation.isPending}
                        className="cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                        title={isSelf ? t("admin.cannotModifySelf") : undefined}
                      >
                        <StatusBadge
                          status={user.isActive ? t("admin.userActive") : t("admin.userInactive")}
                        />
                      </button>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">
                      {new Date(user.createdAt).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => handleDelete(user)}
                        disabled={isSelf || deleteMutation.isPending}
                        className="rounded p-1.5 text-muted-foreground hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/50 dark:hover:text-red-400 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                        title={isSelf ? t("admin.cannotModifySelf") : undefined}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function AdminUsersPage() {
  return (
    <AdminLayout>
      <UsersContent />
    </AdminLayout>
  );
}
