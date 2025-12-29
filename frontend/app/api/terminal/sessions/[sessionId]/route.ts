import { NextRequest, NextResponse } from "next/server";

const TERMINAL_SERVICE_URL = process.env.TERMINAL_SERVICE_URL || "http://localhost:8002";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  try {
    const { sessionId } = await params;
    const res = await fetch(`${TERMINAL_SERVICE_URL}/api/terminal/sessions/${sessionId}`);
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error("Terminal proxy error:", error);
    return NextResponse.json({ error: "Terminal service unavailable" }, { status: 503 });
  }
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  try {
    const { sessionId } = await params;
    const body = await request.json();
    const res = await fetch(`${TERMINAL_SERVICE_URL}/api/terminal/sessions/${sessionId}`, {
      method: "PATCH",
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

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  try {
    const { sessionId } = await params;
    const res = await fetch(`${TERMINAL_SERVICE_URL}/api/terminal/sessions/${sessionId}`, {
      method: "DELETE",
    });
    if (res.status === 204 || res.ok) {
      return NextResponse.json({ deleted: true, id: sessionId });
    }
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (error) {
    console.error("Terminal proxy error:", error);
    return NextResponse.json({ error: "Terminal service unavailable" }, { status: 503 });
  }
}
