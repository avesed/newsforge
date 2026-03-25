import { Navigate } from "react-router-dom";

/**
 * Legacy route — redirects to the new admin overview page.
 * This file can be removed once all references to it are cleaned up.
 */
export default function AdminPage() {
  return <Navigate to="/admin" replace />;
}
