export type Dict<T = unknown> = Record<string, T>;

export type Principal = {
  user_id: string;
  role: "student" | "professor" | "ta" | "uni_admin" | "admin";
  tenant_id: string;
  permissions: string[];
  is_global_admin: boolean;
  groups?: string[];
  provider?: string;
  staff_id?: number | null;
  student_group_id?: number | null;
};

export type OrganizationMembership = {
  tenant_id: string;
  display_name: string;
  role: Principal["role"];
  enabled: boolean;
  active: boolean;
  group_count: number;
};

export type Instance = {
  days: string[];
  weeks: number[];
  slots_per_day: number;
  activities: Dict<Dict>;
  courses: Dict<Dict>;
  staff: Dict<Dict>;
  rooms: Dict<Dict>;
  groups: Dict<Dict>;
};

export type Schedule = Dict<Dict>;

export type WorkspaceState = {
  instance: Instance | null;
  schedule: Schedule;
  sessionId: string;
  score: Dict;
  conflicts: string[];
};

export type ViewKey =
  | "home"
  | "faq"
  | "login"
  | "account"
  | "workspace"
  | "review"
  | "operations"
  | "settings"
  | "fairness"
  | "projects"
  | "parity"
  | "access"
  | "admin";
