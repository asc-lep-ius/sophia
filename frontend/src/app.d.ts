import type { Locale } from "$lib/i18n/locale";

type SophiaRole = "admin" | "instructor" | "student";

type SophiaUser = {
  id: string;
  email?: string;
  name: string;
};

type SophiaTenant = {
  org_id: string;
  course_id: string;
  role: SophiaRole;
};

declare global {
  namespace App {
    interface Locals {
      user: SophiaUser | null;
      org_id: string;
      course_id: string;
      role: SophiaRole;
      locale: Locale;
      tenant: SophiaTenant;
      request_id: string;
      apiSetCookies: string[];
    }

    interface PageData {
      locale: Locale;
      tenant: SophiaTenant;
      theme: import("$lib/theme").Theme;
    }
  }
}

export {};
