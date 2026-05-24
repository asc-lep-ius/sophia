import createClient, { type ClientOptions } from "openapi-fetch";

import type { paths } from "./schema";

type JsonPrimitive = boolean | number | string | null;

export type ApiPath = keyof paths & string;

export type ApiErrorDetail = {
  code: string;
  params: Record<string, JsonPrimitive>;
};

export type NormalizedApiError = {
  detail: ApiErrorDetail;
  requestId?: string;
  status: number;
};

type ErrorEnvelope = {
  detail?: {
    code?: unknown;
    params?: unknown;
  };
};

type ApiResult<Data, ErrorBody> =
  | {
      data: Data;
      error?: never;
      response: Response;
    }
  | {
      data?: never;
      error: ErrorBody;
      response: Response;
    };

type NormalizedDateValue<T> = T extends string
  ? string | Date
  : T extends Array<infer Item>
    ? NormalizedDateValue<Item>[]
    : T extends object
      ? { [Key in keyof T]: NormalizedDateValue<T[Key]> }
      : T;

const ISO_DATETIME_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

export class SophiaApiError extends Error {
  readonly detail: ApiErrorDetail;
  readonly requestId?: string;
  readonly status: number;

  constructor(error: NormalizedApiError) {
    super(error.detail.code);
    this.name = "SophiaApiError";
    this.detail = error.detail;
    this.requestId = error.requestId;
    this.status = error.status;
  }
}

export function createApiClient(options: ClientOptions = {}) {
  return createClient<paths>({
    baseUrl: "",
    ...options,
  });
}

export async function unwrapApiResponse<Data, ErrorBody>(
  resultPromise: Promise<ApiResult<Data, ErrorBody>>,
): Promise<NormalizedDateValue<Data>> {
  const result = await resultPromise;
  const requestId = result.response.headers.get("x-request-id") ?? undefined;

  if (result.error !== undefined || !result.response.ok) {
    throw new SophiaApiError(
      normalizeApiError(result.error, result.response.status, requestId),
    );
  }

  return normalizeIsoDatetimes(result.data) as NormalizedDateValue<Data>;
}

export function normalizeApiError(
  body: unknown,
  status: number,
  requestId?: string,
): NormalizedApiError {
  const envelope = body as ErrorEnvelope;
  const code =
    typeof envelope?.detail?.code === "string"
      ? envelope.detail.code
      : "http.failed";
  const params = isJsonParams(envelope?.detail?.params)
    ? envelope.detail.params
    : {};

  return {
    detail: { code, params },
    requestId,
    status,
  };
}

export function normalizeIsoDatetimes<T>(value: T): NormalizedDateValue<T> {
  if (typeof value === "string") {
    if (ISO_DATETIME_PATTERN.test(value)) {
      const date = new Date(value);
      if (!Number.isNaN(date.valueOf())) {
        return date as NormalizedDateValue<T>;
      }
    }
    return value as NormalizedDateValue<T>;
  }

  if (Array.isArray(value)) {
    return value.map((item) =>
      normalizeIsoDatetimes(item),
    ) as NormalizedDateValue<T>;
  }

  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, nestedValue]) => [
        key,
        normalizeIsoDatetimes(nestedValue),
      ]),
    ) as NormalizedDateValue<T>;
  }

  return value as NormalizedDateValue<T>;
}

function isJsonParams(value: unknown): value is Record<string, JsonPrimitive> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  return Object.values(value).every(
    (item) =>
      item === null || ["boolean", "number", "string"].includes(typeof item),
  );
}
