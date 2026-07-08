import { NextRequest, NextResponse } from "next/server";

// Simple shared-password gate (PART L: the terminal shows wallet P&L, so it
// is never public). Session cookie is the SHA-256 of DASHBOARD_PASSWORD.

async function tokenFor(password: string): Promise<string> {
  const data = new TextEncoder().encode(`polybot:${password}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function middleware(req: NextRequest) {
  const password = process.env.DASHBOARD_PASSWORD ?? "";
  if (!password) {
    // Fail CLOSED: no password configured means no access.
    return new NextResponse("dashboard locked: DASHBOARD_PASSWORD unset", { status: 503 });
  }
  const expected = await tokenFor(password);
  const cookie = req.cookies.get("polybot_auth")?.value;
  if (cookie === expected) {
    return NextResponse.next();
  }

  if (req.method === "POST" && req.nextUrl.pathname === "/login") {
    const form = await req.formData().catch(() => null);
    if (form && form.get("password") === password) {
      const res = NextResponse.redirect(new URL("/", req.url), 303);
      res.cookies.set("polybot_auth", expected, {
        httpOnly: true,
        secure: true,
        sameSite: "strict",
        maxAge: 60 * 60 * 24 * 30,
        path: "/",
      });
      return res;
    }
  }

  return new NextResponse(
    `<!doctype html><html><head><title>polybot login</title></head>
<body style="background:#0b0e11;color:#d1d5db;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<form method="POST" action="/login" style="text-align:center">
<div style="margin-bottom:12px;letter-spacing:2px">POLYBOT TERMINAL</div>
<input type="password" name="password" placeholder="password" autofocus
 style="background:#111827;color:#d1d5db;border:1px solid #374151;padding:8px 12px;font-family:monospace"/>
<button type="submit" style="background:#1f2937;color:#d1d5db;border:1px solid #374151;padding:8px 14px;margin-left:6px;font-family:monospace;cursor:pointer">enter</button>
</form></body></html>`,
    { status: 401, headers: { "content-type": "text/html" } }
  );
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
