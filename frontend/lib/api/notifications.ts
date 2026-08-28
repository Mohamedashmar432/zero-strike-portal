import { apiFetch } from "./client";

export interface Notification {
  id: string;
  event: string;
  title: string;
  body: string;
  severity: "info" | "success" | "warning" | "error";
  project_id: string | null;
  link: string | null;
  read_at: string | null;
  created_at: string;
}

export interface NotificationList {
  items: Notification[];
  unread_count: number;
}

export interface NotificationEvent {
  key: string;
  label: string;
  description: string;
  /** "admin" events are only ever delivered to portal admins, whatever a user subscribes to. */
  audience: "project" | "admin";
}

export interface NotificationPreferences {
  events: NotificationEvent[];
  in_app: string[];
  email: string[];
  /** False until SMTP is configured — email preferences save, but nothing is sent yet. */
  email_delivery_configured: boolean;
}

export function listNotifications(limit = 50) {
  return apiFetch<NotificationList>(`/notifications?limit=${limit}`);
}

/** Omit `notificationId` to mark every unread notification read. */
export function markNotificationsRead(notificationId?: string) {
  return apiFetch<NotificationList>("/notifications/read", {
    method: "POST",
    body: JSON.stringify({ notification_id: notificationId ?? null }),
  });
}

export function getNotificationPreferences() {
  return apiFetch<NotificationPreferences>("/notifications/preferences");
}

export function updateNotificationPreferences(payload: { in_app?: string[]; email?: string[] }) {
  return apiFetch<NotificationPreferences>("/notifications/preferences", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
