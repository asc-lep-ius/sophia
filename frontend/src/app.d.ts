import type { Locale } from "$lib/i18n/locale";

type SophiaRole = "student" | "peer_instructor" | "ta" | "instructor";

type SophiaUser = {
  displayName: string;
  id: string;
  email?: string;
  name: string;
};

type SophiaTenant = {
  cohort_id?: string | null;
  org_id: string;
  course_id: string;
  role: SophiaRole;
};

type SophiaSessionSettings = {
  locale: string;
  selected_course_id?: string | null;
  theme: string;
};

declare global {
  namespace App {
    interface Locals {
      authenticated: boolean;
      user: SophiaUser | null;
      org_id: string;
      course_id: string;
      role: SophiaRole;
      locale: Locale;
      csrfToken: string | null;
      sessionSettings: SophiaSessionSettings | null;
      tenant: SophiaTenant;
      request_id: string;
      apiSetCookies: string[];
    }

    interface PageData {
      locale: Locale;
      tenant: SophiaTenant;
      theme: import("$lib/theme").Theme;
      authenticated: boolean;
      settings: SophiaSessionSettings | null;
      user: SophiaUser | null;
    }
  }
}

export {};
