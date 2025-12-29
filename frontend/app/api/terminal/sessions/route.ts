import { NextRequest, NextResponse } from "next/server";

const TERMINAL_SERVICE_URL = process.env.TERMINAL_SERVICE_URL || "http://localhost:8002";

export async function GET() {
  try {
    const res = await fetch(`${TERMINAL_SERVICE_URL}/api/terminal/sessions`);
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error("Terminal proxy error:", error);
    return NextResponse.json({ error: "Terminal service unavailable" }, { status: 503 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const res = await fetch(`${TERMINAL_SERVICE_URL}/api/terminal/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error("Terminal proxy error:", error);
    return NextResponse.json({ error: "Terminal service unavailable" }, { status: 503 });
  }
}
