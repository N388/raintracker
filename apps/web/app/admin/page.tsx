"use client";

import { useCallback, useEffect, useState } from "react";

const HOST = typeof window !== "undefined" ? window.location.hostname : "localhost";
const API = process.env.NEXT_PUBLIC_API_URL ?? `http://${HOST}:8080/api/v1`;

type Tab = "dash" | "etl" | "layers" | "settings" | "logs";

export default function AdminPage() {
  const [token, setToken] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("dash");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    const t = sessionStorage.getItem("admin_token");
    if (t) setToken(t);
  }, []);

  const login = async () => {
    const r = await fetch(`${API}/admin/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (r.ok) {
      const d = await r.json();
      sessionStorage.setItem("admin_token", d.access_token);
      setToken(d.access_token);
    } else setErr("فشل تسجيل الدخول");
  };

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-stone-100" dir="rtl">
        <div className="bg-white p-6 rounded-2xl shadow w-80">
          <h1 className="text-xl font-bold mb-4">لوحة التحكم — مطر</h1>
          <input className="w-full border rounded-lg p-2 mb-2" placeholder="البريد" value={email} onChange={e => setEmail(e.target.value)} />
          <input className="w-full border rounded-lg p-2 mb-3" type="password" placeholder="كلمة المرور" value={password} onChange={e => setPassword(e.target.value)} />
          <button onClick={login} className="w-full bg-sky-700 text-white rounded-lg py-2">دخول</button>
          {err && <div className="text-red-600 text-sm mt-2">{err}</div>}
        </div>
      </div>
    );
  }

  const authed = { Authorization: `Bearer ${token}` };
  const tabs: [Tab, string][] = [["dash", "لوحة القيادة"], ["etl", "ETL"], ["layers", "الطبقات"], ["settings", "الإعدادات"], ["logs", "السجلات"]];

  return (
    <div className="min-h-screen bg-stone-100" dir="rtl">
      <header className="bg-white shadow-sm p-3 flex gap-2 items-center flex-wrap">
        <span className="font-bold ml-3">مطر — الإدارة</span>
        {tabs.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-3 py-1 rounded-full text-sm ${tab === k ? "bg-sky-700 text-white" : "bg-stone-200"}`}>
            {label}
          </button>
        ))}
        <button className="mr-auto text-sm text-stone-500"
          onClick={() => { sessionStorage.removeItem("admin_token"); setToken(null); }}>خروج</button>
      </header>
      <main className="p-4 max-w-4xl mx-auto">
        {tab === "dash" && <Dash authed={authed} />}
        {tab === "etl" && <Etl authed={authed} />}
        {tab === "layers" && <Layers authed={authed} />}
        {tab === "settings" && <Settings authed={authed} />}
        {tab === "logs" && <Logs authed={authed} />}
      </main>
    </div>
  );
}

function useJson(authed: Record<string, string>, url: string, deps: unknown[] = []) {
  const [data, setData] = useState<any>(null);
  const reload = useCallback(() => {
    fetch(url, { headers: authed }).then(r => (r.ok ? r.json() : null)).then(setData).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, ...deps]);
  useEffect(reload, [reload]);
  return { data, reload };
}

function Dash({ authed }: { authed: Record<string, string> }) {
  const { data } = useJson(authed, `${API}/admin/stats`);
  const { data: runs } = useJson(authed, `${API}/admin/etl/runs`);
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {[["أيام المطر", data?.rain_days], ["قيم الخلايا", data?.rain_values?.toLocaleString?.("ar")], ["الطبقات المفعّلة", data?.enabled_layers], ["آخر تشغيلات", runs?.length]].map(([l, v]) => (
        <div key={l as string} className="bg-white rounded-xl p-4 shadow">
          <div className="text-2xl font-bold">{v ?? "—"}</div>
          <div className="text-stone-500 text-sm">{l}</div>
        </div>
      ))}
    </div>
  );
}

function Etl({ authed }: { authed: Record<string, string> }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  const { data: runs, reload } = useJson(authed, `${API}/admin/etl/runs`);
  const run = async () => {
    setBusy(true);
    const r = await fetch(`${API}/admin/etl/run`, { method: "POST", headers: authed });
    setResult(r.ok ? JSON.stringify(await r.json()) : "فشل");
    setBusy(false);
    reload();
  };
  return (
    <div>
      <button onClick={run} disabled={busy}
        className="bg-emerald-700 text-white px-4 py-2 rounded-lg disabled:opacity-50">
        {busy ? "يعمل…" : "تشغيل ETL الآن"}
      </button>
      {result && <pre className="bg-white p-3 rounded-lg mt-3 text-xs overflow-auto" dir="ltr">{result}</pre>}
      <h3 className="font-bold mt-5 mb-2">آخر التشغيلات</h3>
      <table className="w-full bg-white rounded-lg text-sm">
        <thead><tr className="border-b"><th className="p-2 text-right">#</th><th className="p-2 text-right">الوظيفة</th><th className="p-2 text-right">الحالة</th><th className="p-2 text-right">التوقيت</th></tr></thead>
        <tbody>{(runs ?? []).map((r: any) => (
          <tr key={r.id} className="border-b"><td className="p-2">{r.id}</td><td className="p-2">{r.job}</td><td className="p-2">{r.status}</td><td className="p-2 text-xs">{r.started_at}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function Layers({ authed }: { authed: Record<string, string> }) {
  const { data, reload } = useJson(authed, `${API}/admin/layers`);
  const toggle = async (key: string, enabled: boolean) => {
    await fetch(`${API}/admin/layers/${key}`, { method: "PUT", headers: { ...authed, "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
    reload();
  };
  return (
    <table className="w-full bg-white rounded-lg text-sm">
      <thead><tr className="border-b"><th className="p-2 text-right">المفتاح</th><th className="p-2 text-right">الاسم</th><th className="p-2 text-right">المجموعة</th><th className="p-2 text-right">مفعّلة</th></tr></thead>
      <tbody>{(data ?? []).map((l: any) => (
        <tr key={l.key} className="border-b">
          <td className="p-2 font-mono text-xs">{l.key}</td><td className="p-2">{l.name_ar}</td><td className="p-2">{l.group_ar}</td>
          <td className="p-2"><input type="checkbox" checked={l.enabled} onChange={e => toggle(l.key, e.target.checked)} /></td>
        </tr>
      ))}</tbody>
    </table>
  );
}

function Settings({ authed }: { authed: Record<string, string> }) {
  const { data, reload } = useJson(authed, `${API}/admin/settings`);
  const [wasmStart, setWasmStart] = useState("10-16");
  const [wasmLen, setWasmLen] = useState(52);
  useEffect(() => { if (data?.wasm) { setWasmStart(data.wasm.start); setWasmLen(data.wasm.length_days); } }, [data]);
  const save = async () => {
    await fetch(`${API}/admin/settings/wasm`, { method: "PUT", headers: { ...authed, "Content-Type": "application/json" },
      body: JSON.stringify({ value: { start: wasmStart, length_days: wasmLen } }) });
    reload();
  };
  return (
    <div className="bg-white rounded-xl p-4 shadow max-w-md">
      <h3 className="font-bold mb-3">الوسم</h3>
      <label className="block text-sm mb-2">تاريخ البداية (شهر-يوم)
        <input className="block border rounded p-1 mt-1" dir="ltr" value={wasmStart} onChange={e => setWasmStart(e.target.value)} /></label>
      <label className="block text-sm mb-3">المدة (أيام)
        <input className="block border rounded p-1 mt-1 w-24" type="number" value={wasmLen} onChange={e => setWasmLen(+e.target.value)} /></label>
      <button onClick={save} className="bg-sky-700 text-white px-4 py-1.5 rounded-lg">حفظ</button>
    </div>
  );
}

function Logs({ authed }: { authed: Record<string, string> }) {
  const { data } = useJson(authed, `${API}/admin/logs`);
  return (
    <table className="w-full bg-white rounded-lg text-sm">
      <thead><tr className="border-b"><th className="p-2 text-right">الوقت</th><th className="p-2 text-right">الفاعل</th><th className="p-2 text-right">الإجراء</th></tr></thead>
      <tbody>{(data ?? []).map((l: any) => (
        <tr key={l.id} className="border-b"><td className="p-2 text-xs">{l.at}</td><td className="p-2">{l.actor}</td><td className="p-2">{l.action}</td></tr>
      ))}</tbody>
    </table>
  );
}
