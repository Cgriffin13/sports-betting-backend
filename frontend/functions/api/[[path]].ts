interface Env {
  BACKEND_API_URL: string;
  BACKEND_API_KEY: string;
}

type PagesFunction<TEnv> = (context: {
  request: Request;
  env: TEnv;
  params: Record<string, string | string[]>;
}) => Promise<Response>;

export const onRequest: PagesFunction<Env> = async ({ request, env, params }) => {
  if (!env.BACKEND_API_URL || !env.BACKEND_API_KEY) {
    return Response.json({ detail: "Dashboard backend is not configured" }, { status: 503 });
  }
  if (!new Set(["GET", "POST", "OPTIONS"]).has(request.method)) {
    return Response.json({ detail: "Method not allowed" }, { status: 405 });
  }
  const source = new URL(request.url);
  const suffix = Array.isArray(params.path) ? params.path.join("/") : String(params.path || "");
  const target = new URL(`/${suffix}`, env.BACKEND_API_URL);
  target.search = source.search;
  const headers = new Headers(request.headers);
  headers.delete("cookie");
  headers.delete("authorization");
  headers.set("X-API-Key", env.BACKEND_API_KEY);
  headers.set("Accept", "application/json");
  const response = await fetch(target, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "OPTIONS" ? undefined : request.body,
    redirect: "manual",
  });
  const output = new Headers(response.headers);
  output.set("Cache-Control", "no-store");
  return new Response(response.body, { status: response.status, headers: output });
};
