import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import type { ApiError } from "@/types";
import {
  getAccessToken,
  hardLogout,
  refreshAccessToken,
} from "./tokenRefresh";

type RetryableConfig = InternalAxiosRequestConfig & { _retry?: boolean };

const apiClient = axios.create({
  baseURL: "/api/v1",
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30000,
});

apiClient.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as RetryableConfig | undefined;
    const status = error.response?.status;

    if (status !== 401 || !original || original._retry) {
      return Promise.reject(error);
    }

    // A 401 on /auth/refresh itself means refresh is dead — fall through to logout.
    if (original.url?.endsWith("/auth/refresh")) {
      hardLogout();
      return Promise.reject(error);
    }

    original._retry = true;
    try {
      const newToken = await refreshAccessToken();
      original.headers = original.headers ?? {};
      original.headers.Authorization = `Bearer ${newToken}`;
      return apiClient(original);
    } catch {
      hardLogout();
      return Promise.reject(error);
    }
  }
);

export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as ApiError | undefined;
    if (data?.detail) {
      return data.detail;
    }
    if (error.message) {
      return error.message;
    }
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "An unexpected error occurred";
}

export default apiClient;
